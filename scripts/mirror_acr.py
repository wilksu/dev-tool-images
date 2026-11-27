#!/usr/bin/env python3
"""Mirror tagged public images to ACR, using the remote manifest as sync state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET_NAMES = ("ACR_REGISTRY", "ACR_NAMESPACE", "ACR_USERNAME", "ACR_PASSWORD")
REPOSITORY = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
TAG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
SOURCE = re.compile(rf"[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/(?:{REPOSITORY}/)*{REPOSITORY}:{TAG}")
TARGET = re.compile(rf"({REPOSITORY}):({TAG})")


@dataclass(frozen=True)
class Image:
    source: str
    target: str

    @property
    def repository(self) -> str:
        return self.source.rsplit(":", 1)[0]


def read_images(path: pathlib.Path) -> list[Image]:
    images = []
    targets = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.partition("#")[0].split()
        if not fields:
            continue
        if len(fields) != 2 or not SOURCE.fullmatch(fields[0]):
            raise ValueError(f"{path.name}:{number}: expected fully qualified source:tag and repository:tag")
        match = TARGET.fullmatch(fields[1])
        if not match or not 2 <= len(match[1]) <= 64:
            raise ValueError(f"{path.name}:{number}: ACR target needs a 2-64 character repository name and a tag")
        if fields[1] in targets:
            raise ValueError(f"{path.name}:{number}: duplicate ACR target")
        targets.add(fields[1])
        images.append(Image(*fields))
    if not images:
        raise ValueError("image list is empty")
    return images


def manifest_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def source_digest(raw: bytes) -> str:
    """Unwrap a single runnable image from an index with attestations.

    ACR Personal rejects Mattermost's OCI-empty attestation config. Its sole
    runtime manifest remains byte-for-byte unchanged; multi-platform indexes
    such as nginx are copied intact.
    """
    manifests = json.loads(raw).get("manifests", [])
    runtime = [item for item in manifests if item.get("annotations", {}).get("vnd.docker.reference.type") != "attestation-manifest"]
    if len(runtime) == 1 and len(manifests) > 1:
        digest = runtime[0]["digest"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("upstream runtime manifest has an invalid digest")
        return digest
    return manifest_digest(raw)


class Registry:
    def __init__(self, authfile: pathlib.Path, secrets: dict[str, str]):
        self.authfile = authfile
        self.secrets = secrets
        # Credentials are passed only to login, never inherited by copy/inspect.
        self.environment = {key: value for key, value in os.environ.items() if key not in SECRET_NAMES}

    def redact(self, text: str) -> str:
        for value in sorted(set(self.secrets.values()), key=len, reverse=True):
            if value:
                text = text.replace(value, "***")
        return text

    def run(self, *arguments: str, password: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                ["skopeo", *arguments],
                input=password.encode() if password is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.environment,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("registry operation timed out; rerun to resume") from None

    def require_success(self, result: subprocess.CompletedProcess) -> None:
        if result.returncode:
            error = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(self.redact(error) or "registry operation failed")

    def login(self) -> None:
        result = self.run(
            "login", "--authfile", str(self.authfile),
            "--username", self.secrets["ACR_USERNAME"], "--password-stdin",
            self.secrets["ACR_REGISTRY"], password=self.secrets["ACR_PASSWORD"],
        )
        self.require_success(result)

    def inspect(self, reference: str, *, destination: bool = False) -> str | None:
        authentication = ["--authfile", str(self.authfile)] if destination else ["--no-creds"]
        result = self.run("inspect", "--raw", "--retry-times", "3", *authentication, f"docker://{reference}")
        if result.returncode:
            error = result.stderr.decode(errors="replace").lower()
            # Authentication, throttling and network errors must fail, not masquerade as an absent image.
            if destination and any(marker in error for marker in ("manifest unknown", "manifest_unknown", "name unknown", "name_unknown")):
                return None
            self.require_success(result)
        return manifest_digest(result.stdout) if destination else source_digest(result.stdout)

    def copy(self, source: str, destination: str) -> None:
        result = self.run(
            "copy", "--all", "--preserve-digests", "--retry-times", "3",
            "--src-no-creds", "--dest-authfile", str(self.authfile),
            f"docker://{source}", f"docker://{destination}", timeout=1800,
        )
        self.require_success(result)


def synchronize(image: Image, prefix: str, registry: Registry) -> tuple[str, str]:
    digest = registry.inspect(image.source)
    destination = f"{prefix}/{image.target}"
    if registry.inspect(destination, destination=True) == digest:
        return "unchanged", digest
    # Pin the source after resolving its moving tag to avoid a tag-update race.
    registry.copy(f"{image.repository}@{digest}", destination)
    if registry.inspect(destination, destination=True) != digest:
        raise RuntimeError("destination digest does not match the resolved upstream digest")
    return "copied", digest


def append_summary(text: str) -> None:
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as output:
            output.write(text)


def credentials() -> dict[str, str]:
    values = {name: os.environ.get(name, "") for name in SECRET_NAMES}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError("missing GitHub Actions Secrets: " + ", ".join(missing))
    if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?", values["ACR_REGISTRY"]):
        raise ValueError("ACR_REGISTRY must be a hostname without https:// or a path")
    if not re.fullmatch(REPOSITORY, values["ACR_NAMESPACE"]):
        raise ValueError("ACR_NAMESPACE must contain only the namespace name")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", type=pathlib.Path, default=ROOT / "mirrors/images.txt")
    parser.add_argument("--check", action="store_true", help="validate the list without secrets or registry requests")
    args = parser.parse_args()
    images = read_images(args.list)
    if args.check:
        print(f"Validated {len(images)} mirror entries")
        return 0

    secrets = credentials()
    prefix = f"{secrets['ACR_REGISTRY']}/{secrets['ACR_NAMESPACE']}"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    append_summary(f"## ACR image synchronization\n\nChecked at {timestamp}. All upstream platforms are preserved.\n\n"
                   "| Upstream | Target within ACR namespace | Result | Manifest digest |\n"
                   "| --- | --- | --- | --- |\n")
    failures = 0
    with tempfile.TemporaryDirectory(prefix="acr-auth-") as directory:
        registry = Registry(pathlib.Path(directory) / "auth.json", secrets)
        registry.login()
        for image in images:
            print(f"Checking {image.source}", flush=True)
            try:
                status, digest = synchronize(image, prefix, registry)
                print(f"{image.source}: {status} ({digest})", flush=True)
                append_summary(f"| `{image.source}` | `{image.target}` | {status} | `{digest}` |\n")
            except RuntimeError as error:
                failures += 1
                print(f"{image.source}: FAILED: {registry.redact(str(error))}", file=sys.stderr, flush=True)
                append_summary(f"| `{image.source}` | `{image.target}` | FAILED; see step log | — |\n")
    return int(failures > 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as error:
        # Do not include command arguments or credential values in a traceback.
        message = str(error)
        for name in SECRET_NAMES:
            if value := os.environ.get(name):
                message = message.replace(value, "***")
        print(f"Synchronization failed: {message}", file=sys.stderr)
        sys.exit(1)
