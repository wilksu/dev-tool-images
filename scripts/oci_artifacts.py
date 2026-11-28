#!/usr/bin/env python3
"""Verify and assemble already-built OCI candidates without rebuilding images."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import tarfile


INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def blob_path(layout: pathlib.Path, digest: str) -> pathlib.Path:
    if not DIGEST.fullmatch(digest):
        raise ValueError("invalid OCI digest")
    return layout / "blobs" / "sha256" / digest.split(":", 1)[1]


def read_blob(layout: pathlib.Path, digest: str) -> dict:
    path = blob_path(layout, digest)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("oversized OCI JSON blob")
    raw = path.read_bytes()
    if digest_bytes(raw) != digest:
        raise ValueError("OCI blob digest mismatch")
    return json.loads(raw)


def root_digest(layout: pathlib.Path, expected: str | None = None) -> str:
    raw = (layout / "index.json").read_bytes()
    if expected:
        path = blob_path(layout, expected)
        if not path.exists() and digest_bytes(raw) == expected:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        read_blob(layout, expected)
        return expected
    descriptors = json.loads(raw)["manifests"]
    if len(descriptors) > 1:
        # BuildKit may export the image index directly as index.json rather
        # than placing a one-descriptor layout index in front of it.
        return root_digest(layout, digest_bytes(raw))
    if len(descriptors) != 1:
        raise ValueError("OCI layout must identify exactly one root")
    digest = descriptors[0]["digest"]
    read_blob(layout, digest)
    return digest


def unpack(archive: pathlib.Path, destination: pathlib.Path) -> pathlib.Path:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if len(members) > 20000 or sum(member.size for member in members) > 16 * 1024 ** 3:
            raise ValueError("OCI archive exceeds limits")
        for member in members:
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe OCI archive member")
        source.extractall(destination, members=members, filter="data")
    return destination


def verify_graph(layout: pathlib.Path, root: str) -> None:
    seen = set()

    def visit(descriptor: dict, document: bool) -> None:
        digest = descriptor["digest"]
        if digest in seen:
            return
        seen.add(digest)
        if len(seen) > 20000:
            raise ValueError("OCI graph exceeds limits")
        path = blob_path(layout, digest)
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing or non-regular OCI blob")
        if "size" in descriptor and path.stat().st_size != descriptor["size"]:
            raise ValueError("OCI descriptor size mismatch")
        with path.open("rb") as source:
            actual = "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()
        if actual != digest:
            raise ValueError("OCI blob digest mismatch")
        if document:
            value = read_blob(layout, digest)
            if "manifests" in value:
                for child in value["manifests"]:
                    visit(child, True)
            else:
                visit(value["config"], False)
                for layer in value["layers"]:
                    visit(layer, False)
    visit({"digest": root}, True)


def leaves(layout: pathlib.Path, root: str) -> list[dict]:
    result = []

    def visit(digest: str, descriptor: dict | None = None) -> None:
        document = read_blob(layout, digest)
        if "manifests" in document:
            for child in document["manifests"]:
                visit(child["digest"], child)
        else:
            item = dict(descriptor or {"mediaType": document.get("mediaType", MANIFEST),
                                       "size": blob_path(layout, digest).stat().st_size, "digest": digest})
            if item.get("annotations", {}).get("vnd.docker.reference.type") != "attestation-manifest":
                config = read_blob(layout, document["config"]["digest"])
                platform = {"os": config["os"], "architecture": config["architecture"]}
                if platform["os"] != "linux" or platform["architecture"] not in {"amd64", "arm64"}:
                    raise ValueError("unexpected runtime platform")
                if "platform" in item and any(item["platform"].get(key) != value for key, value in platform.items()):
                    raise ValueError("OCI platform descriptor does not match its config")
                item["platform"] = {**item.get("platform", {}), **platform}
            result.append(item)
    visit(root)
    return result


def runtime_entries(layout: pathlib.Path, root: str) -> dict[str, dict]:
    result = {}
    for item in leaves(layout, root):
        if item.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest":
            continue
        platform = item["platform"]
        key = f"{platform['os']}/{platform['architecture']}"
        if key in result:
            raise ValueError("duplicate OCI runtime platform")
        result[key] = item
    return result


def verify_candidate(layout: pathlib.Path, root: str, image: str, revision: str, platform: str) -> dict:
    verify_graph(layout, root)
    entries = runtime_entries(layout, root)
    if set(entries) != {platform}:
        raise ValueError("candidate does not contain exactly the requested platform")
    runtime = entries[platform]
    manifest = read_blob(layout, runtime["digest"])
    config = read_blob(layout, manifest["config"]["digest"])
    labels = config.get("config", {}).get("Labels", {})
    if labels.get("org.opencontainers.image.revision") != revision or labels.get("io.starferry.tool.name") != image:
        raise ValueError("candidate source identity mismatch")
    return {"schema": 1, "image": image, "revision": revision, "platform": platform,
            "digest": root, "config_digest": manifest["config"]["digest"]}


def runtime_view(layout: pathlib.Path, root: str, platform: str, destination: pathlib.Path) -> pathlib.Path:
    descriptor = runtime_entries(layout, root)[platform]
    destination.mkdir()
    (destination / "oci-layout").write_bytes(encode({"imageLayoutVersion": "1.0.0"}))
    (destination / "index.json").write_bytes(encode({"schemaVersion": 2, "mediaType": INDEX, "manifests": [descriptor]}))
    (destination / "blobs").symlink_to((layout / "blobs").resolve(), target_is_directory=True)
    return destination


def combine(candidates: list[tuple[pathlib.Path, dict]], destination: pathlib.Path,
            image: str, revision: str, platforms: list[str]) -> str:
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "blobs" / "sha256").mkdir(parents=True)
    entries, observed, seen = [], set(), set()
    for layout, receipt in sorted(candidates, key=lambda item: item[1]["platform"]):
        if receipt.get("verified") is not True:
            raise ValueError("candidate has not passed runtime verification")
        platform = receipt["platform"]
        if platform in observed:
            raise ValueError("duplicate candidate platform")
        root_digest(layout, receipt["digest"])
        actual = verify_candidate(layout, receipt["digest"], image, revision, platform)
        if any(receipt.get(key) != value for key, value in actual.items()):
            raise ValueError("candidate receipt does not match OCI content")
        observed.add(platform)
        for descriptor in leaves(layout, receipt["digest"]):
            identity = encode(descriptor)
            if identity not in seen:
                entries.append(descriptor)
                seen.add(identity)
        for source in (layout / "blobs" / "sha256").iterdir():
            target = destination / "blobs" / "sha256" / source.name
            if not target.exists():
                os.link(source, target)
    if observed != set(platforms):
        raise ValueError("missing or unexpected candidate platforms")
    raw = encode({"schemaVersion": 2, "mediaType": INDEX, "manifests": entries})
    digest = digest_bytes(raw)
    blob_path(destination, digest).write_bytes(raw)
    (destination / "oci-layout").write_bytes(encode({"imageLayoutVersion": "1.0.0"}))
    (destination / "index.json").write_bytes(encode({"schemaVersion": 2, "mediaType": INDEX,
        "manifests": [{"mediaType": INDEX, "size": len(raw), "digest": digest}]}))
    return digest
