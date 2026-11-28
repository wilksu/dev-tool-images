#!/usr/bin/env python3
"""Publish verified OCI candidates to GHCR and emit a run-scoped delivery record."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

from github_api import GitHub
from image_config import ROOT, ci_matrix, load_catalog, write_github_output
from mirror_acr import Registry
from oci_artifacts import blob_path, combine, unpack
from release_records import make_record, validate_record
from resolve_release import resolve_release


def existing_record(github: GitHub, tag: str) -> dict | None:
    release = github.release(tag)
    record = github.release_record(release) if release is not None else None
    if record is not None:
        validate_record(record)
        if record["release_tag"] != tag:
            raise ValueError("release record does not match its Git tag")
    return record


def remote_digest(registry: Registry, github: GitHub, image: str, destination: str) -> str | None:
    try:
        return registry.inspect(destination, destination=True)
    except RuntimeError:
        # A brand-new GHCR package can deny even the authenticated pull-token
        # request. Confirm package absence through GitHub instead of treating
        # arbitrary authentication or network failures as a missing tag.
        if not github.package_exists(image):
            return None
        raise


def require_same_release(record: dict, outputs: dict) -> None:
    if record["image"] != outputs["image_name"] or record["revision"] != outputs["revision"]:
        raise ValueError("release source identity changed")


def probe(registry: Registry, github: GitHub, outputs: dict, record: dict | None) -> bool:
    current = remote_digest(registry, github, outputs["image_name"], outputs["discovery_tag"])
    if current is not None:
        if record is None:
            raise ValueError("unrecorded GHCR tag already exists; import it instead of rebuilding or replacing it")
        if current != record["source"].split("@", 1)[1]:
            raise ValueError("immutable GHCR revision tag was changed")
        return False
    return True


def verify_public(outputs: dict, record: dict, environment: dict[str, str]) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_manifest.py"),
                    "--image", outputs["image"], "--revision", outputs["revision"],
                    "--digest", record["source"].split("@", 1)[1],
                    "--platforms", ",".join(record["platforms"])],
                   check=True, env=environment)


def publish_candidates(registry: Registry, github: GitHub, outputs: dict, candidates: pathlib.Path,
                       work: pathlib.Path, run_id: int, record: dict | None) -> dict:
    selected = []
    expected = outputs["platforms"].split(",")
    directories = list(candidates.glob("candidate-*"))
    wanted = {f"candidate-{outputs['image_name']}-{platform.split('/')[1]}" for platform in expected}
    if {directory.name for directory in directories} != wanted:
        raise ValueError("candidate artifacts do not match the release platform matrix")
    for directory in directories:
        receipt_path = directory / "candidate.json"
        if receipt_path.stat().st_size > 65536:
            raise ValueError("oversized candidate receipt")
        receipt = json.loads(receipt_path.read_text())
        layout = unpack(directory / "image.tar", work / directory.name)
        selected.append((layout, receipt))
    combined = work / "combined"
    digest = combine(selected, combined, outputs["image_name"], outputs["revision"], expected)
    if record is None:
        record = make_record(outputs["image_name"], outputs["revision"], digest,
                             blob_path(combined, digest).read_bytes(), run_id)
    elif record["source"].split("@", 1)[1] != digest:
        raise ValueError("retry candidates do not match the recorded digest")
    # Persist verified intent before writing the discovery tag. A retry can
    # reuse the original run's artifacts or its already-published GHCR image.
    github.save_record(record)
    result = registry.run("copy", "--all", "--preserve-digests", "--retry-times", "3",
                          "--dest-authfile", str(registry.authfile),
                          f"oci:{combined}", f"docker://{outputs['discovery_tag']}", timeout=600)
    registry.require_success(result)
    if remote_digest(registry, github, outputs["image_name"], outputs["discovery_tag"]) != digest:
        raise ValueError("published GHCR digest differs from the verified candidate")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "probe", "publish", "finalize"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--candidates", type=pathlib.Path)
    parser.add_argument("--notification", type=pathlib.Path)
    args = parser.parse_args()
    catalog = load_catalog()
    if os.environ.get("GITHUB_REPOSITORY", catalog["source_repository"]) != catalog["source_repository"]:
        raise ValueError("publication is restricted to the canonical repository")
    outputs, _ = resolve_release(args.tag, args.revision)
    github = GitHub(catalog["source_repository"])
    if github.tag_revision(args.tag) != args.revision:
        raise ValueError("Git tag does not match the requested source commit")
    github.require_mainline(args.revision)
    record = existing_record(github, args.tag)
    if record is not None:
        require_same_release(record, outputs)
    if args.operation == "prepare":
        matrix = ci_matrix(catalog, [outputs["image_name"]]) if record is None else {"include": []}
        for key, value in outputs.items():
            write_github_output(key, value)
        write_github_output("build", str(record is None).lower())
        write_github_output("matrix", json.dumps(matrix, separators=(",", ":")))
        return
    if args.operation == "finalize":
        if record is None or args.notification is None:
            raise ValueError("successful publication record and notification path required")
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"GH_TOKEN", "GITHUB_TOKEN", "GHCR_TOKEN"}}
        verify_public(outputs, record, environment)
        github.complete_release(github.save_record(record))
        notification = {"schema": 1, "publisher_run_id": args.run_id, "record": record}
        args.notification.write_text(json.dumps(notification, indent=2) + "\n")
        return
    token = os.environ["GH_TOKEN"]
    actor = os.environ["GITHUB_ACTOR"]
    with tempfile.TemporaryDirectory(prefix="ghcr-publish-") as directory:
        registry = Registry(pathlib.Path(directory) / "auth.json", {"GHCR_TOKEN": token})
        registry.login(hostname="ghcr.io", username=actor, password=token)
        needed = probe(registry, github, outputs, record)
        if args.operation == "probe":
            write_github_output("needed", str(needed).lower())
            write_github_output("artifact_run_id", str(record["source_run_id"] if record else args.run_id))
            return
        if needed:
            if args.candidates is None:
                raise ValueError("candidate artifacts required for initial publication")
            record = publish_candidates(registry, github, outputs, args.candidates.resolve(),
                                        pathlib.Path(directory), args.run_id, record)
        verify_public(outputs, record, registry.environment)
        write_github_output("digest", record["source"].split("@", 1)[1])


if __name__ == "__main__":
    main()
