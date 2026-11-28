#!/usr/bin/env python3
"""Validate generated owned-image records and translate them into delivery requests."""

from __future__ import annotations

import base64
import json
import pathlib
import re

from image_config import ROOT, RUNNERS, load_catalog
from mirror_acr import Image, SyncRequest, manifest_digest, runtime_index


SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def validate_record(record: dict, catalog: dict | None = None, *, imported: bool = False) -> dict:
    catalog = catalog or load_catalog()
    required = {"schema", "kind", "repository", "image", "revision", "release_tag", "source_run_id",
                "source", "target", "platforms", "copy_mode", "acr_digest", "acr_manifest"}
    if not isinstance(record, dict) or set(record) != required or type(record["schema"]) is not int or record["schema"] != 1:
        raise ValueError("invalid release record shape")
    if any(not isinstance(record[key], str) for key in
           ("kind", "repository", "image", "source", "target", "copy_mode", "acr_digest")):
        raise ValueError("release identity fields must be strings")
    if record["repository"] != catalog["source_repository"] or record["image"] not in catalog["images"]:
        raise ValueError("release record belongs to an unknown repository or image")
    name = record["image"]
    entry = catalog["images"][name]
    source = record["source"]
    prefix = entry["registry"] + "@"
    if not isinstance(source, str) or not source.startswith(prefix) or not DIGEST.fullmatch(source[len(prefix):]):
        raise ValueError("release source must be a pinned owned GHCR image")
    platforms = record["platforms"]
    if (not isinstance(platforms, list) or not platforms or any(not isinstance(p, str) for p in platforms)
            or len(platforms) != len(set(platforms))
            or any(platform not in RUNNERS for platform in platforms)):
        raise ValueError("invalid release platforms")
    if imported:
        if record["kind"] != "imported" or record["source_run_id"] is not None or record["release_tag"] is not None:
            raise ValueError("invalid imported release identity")
        if record["revision"] is not None and (not isinstance(record["revision"], str) or not SHA.fullmatch(record["revision"])):
            raise ValueError("invalid imported revision")
        if not re.fullmatch(re.escape(name) + r":sha-[0-9a-f]{12,40}", record["target"]):
            raise ValueError("invalid historical target alias")
    else:
        revision = record["revision"]
        if (record["kind"] != "published" or not isinstance(revision, str) or not SHA.fullmatch(revision)
                or record["release_tag"] != f"{name}/rev-{revision}"
                or record["target"] != f"{entry['acr_repository']}:sha-{revision}"
                or type(record["source_run_id"]) is not int or record["source_run_id"] <= 0):
            raise ValueError("invalid published release identity")
    if record["copy_mode"] not in {"exact", "runtime-only"} or not DIGEST.fullmatch(record["acr_digest"]):
        raise ValueError("invalid ACR delivery identity")
    if record["acr_manifest"] is None:
        if record["acr_digest"] != source[len(prefix):]:
            raise ValueError("exact delivery must retain the source digest")
    else:
        if record["copy_mode"] != "runtime-only" or not isinstance(record["acr_manifest"], str):
            raise ValueError("unexpected transformed manifest")
        try:
            raw = base64.b64decode(record["acr_manifest"], validate=True)
        except ValueError:
            raise ValueError("invalid encoded ACR manifest") from None
        if len(raw) > 32768 or manifest_digest(raw) != record["acr_digest"]:
            raise ValueError("ACR manifest digest mismatch")
        document = json.loads(raw)
        if not isinstance(document, dict) or document.get("schemaVersion") != 2 or not isinstance(document.get("manifests"), list):
            raise ValueError("invalid ACR runtime index")
        observed = []
        for descriptor in document["manifests"]:
            if (not isinstance(descriptor, dict) or not isinstance(descriptor.get("digest"), str)
                    or not DIGEST.fullmatch(descriptor["digest"])
                    or type(descriptor.get("size")) is not int or descriptor["size"] < 0):
                raise ValueError("invalid runtime manifest digest")
            platform = descriptor.get("platform", {})
            if not isinstance(platform, dict):
                raise ValueError("invalid runtime platform descriptor")
            observed.append(f"{platform.get('os')}/{platform.get('architecture')}")
        if sorted(observed) != sorted(platforms):
            raise ValueError("ACR index does not preserve the declared runtime platforms")
        if runtime_index(raw) != raw:
            raise ValueError("ACR runtime index still contains attestations")
    return record


def make_record(image: str, revision: str, digest: str, raw: bytes, run_id: int,
                catalog: dict | None = None) -> dict:
    catalog = catalog or load_catalog()
    entry = catalog["images"][image]
    if manifest_digest(raw) != digest:
        raise ValueError("source root digest mismatch")
    filtered = runtime_index(raw) if entry["acr_copy_mode"] == "runtime-only" else raw
    record = {
        "schema": 1, "kind": "published", "repository": catalog["source_repository"],
        "image": image, "revision": revision, "release_tag": f"{image}/rev-{revision}",
        "source_run_id": run_id, "source": f"{entry['registry']}@{digest}",
        "target": f"{entry['acr_repository']}:sha-{revision}", "platforms": entry["platforms"],
        "copy_mode": entry["acr_copy_mode"], "acr_digest": manifest_digest(filtered),
        "acr_manifest": base64.b64encode(filtered).decode() if filtered != raw else None,
    }
    return validate_record(record, catalog)


def load_imports(path: pathlib.Path = ROOT / "releases/imported.json") -> list[dict]:
    value = json.loads(path.read_text())
    if set(value) != {"schema", "records"} or value["schema"] != 1:
        raise ValueError("invalid historical release archive")
    records = [validate_record(record, imported=True) for record in value["records"]]
    if len({record["target"] for record in records}) != len(records):
        raise ValueError("duplicate historical target alias")
    return records


def to_request(record: dict) -> SyncRequest:
    validate_record(record, imported=record.get("kind") == "imported")
    raw = base64.b64decode(record["acr_manifest"]) if record["acr_manifest"] is not None else None
    return SyncRequest(Image(record["source"], record["target"], record["copy_mode"] == "runtime-only"),
                       expected_digest=record["acr_digest"], runtime_manifest=raw,
                       preserve_index=record["copy_mode"] == "exact")
