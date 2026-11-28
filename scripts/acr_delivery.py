#!/usr/bin/env python3
"""Reconcile external pins and generated releases, or consume one trusted Publish run."""

from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import re
import sys
import zipfile

from github_api import GitHub
from image_config import ROOT, load_catalog
from mirror_acr import SECRET_NAMES, SyncRequest, read_images, run_requests
from release_records import load_imports, to_request, validate_record


def external_requests(path: pathlib.Path = ROOT / "mirrors/images.txt") -> list[SyncRequest]:
    catalog = load_catalog()
    images = read_images(path)
    for image in images:
        if (image.repository.startswith(f"ghcr.io/{catalog['source_repository']}/")
                or image.target.split(":", 1)[0] in catalog["images"]):
            raise ValueError("owned tool images belong to generated release records, not the external list")
    return [SyncRequest(image) for image in images]


def notification_record(raw: bytes, run_id: int) -> dict:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != "delivery.json" or members[0].file_size > 65536:
            raise ValueError("unexpected release notification archive contents")
        envelope = json.loads(archive.read(members[0]))
    if (not isinstance(envelope, dict) or set(envelope) != {"schema", "publisher_run_id", "record"}
            or envelope["schema"] != 1 or envelope["publisher_run_id"] != run_id):
        raise ValueError("release notification belongs to another run")
    record = validate_record(envelope["record"])
    if record["source_run_id"] != run_id:
        raise ValueError("release was not produced by the notifying run")
    return record


def completed_record(github: GitHub, run_id: int) -> dict:
    """Read JSON only; never check out or execute code from the notifying run."""
    run = github.json("GET", f"{github.prefix}/actions/runs/{run_id}")
    if (run.get("id") != run_id or run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("event") != "push" or run.get("head_repository", {}).get("full_name") != github.repository
            or run.get("repository", {}).get("full_name") != github.repository
            or not re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", ""))):
        raise ValueError("notification is not a successful canonical Publish run")
    workflow = github.json("GET", f"{github.prefix}/actions/workflows/{int(run['workflow_id'])}")
    if workflow.get("path") != ".github/workflows/publish.yml":
        raise ValueError("notification came from an unexpected workflow")
    result = github.json("GET", f"{github.prefix}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = [item for item in result["artifacts"] if item["name"] == "release-record"]
    if len(artifacts) != 1 or artifacts[0].get("expired") or artifacts[0]["size_in_bytes"] > 1024 * 1024:
        raise ValueError("missing or invalid run-scoped release notification")
    raw = github.request("GET", f"{github.prefix}/actions/artifacts/{int(artifacts[0]['id'])}/zip", limit=1024 * 1024)
    record = notification_record(raw, run_id)
    if record["revision"] != run["head_sha"] or github.tag_revision(record["release_tag"]) != record["revision"]:
        raise ValueError("notification source does not match the release tag and run")
    github.require_mainline(record["revision"])
    release = github.release(record["release_tag"])
    if release is None or release.get("draft") or github.release_record(release) != record:
        raise ValueError("notification does not match a completed durable release record")
    return record


def published_records(github: GitHub) -> list[dict]:
    catalog = load_catalog()
    records = []
    prefixes = tuple(entry["release_tag_prefix"] for entry in catalog["images"].values())
    for release in github.pages(f"{github.prefix}/releases"):
        if release.get("draft") or not release["tag_name"].startswith(prefixes):
            continue
        record = github.release_record(release)
        # Historical releases without a generated record are represented by
        # imported.json. Do not invent a new intent from an arbitrary Git tag.
        if record is None:
            continue
        validate_record(record, catalog)
        if record["release_tag"] != release["tag_name"]:
            raise ValueError("durable release record belongs to a different tag")
        records.append(record)
    return records


def select_requests(requests: list[SyncRequest], selection: str = "") -> list[SyncRequest]:
    unique = {}
    for request in requests:
        target = request.image.target
        if target in unique and unique[target] != request:
            raise ValueError(f"conflicting delivery intents for {target}")
        unique[target] = request
    requests = list(unique.values())
    if not selection:
        return requests
    requested = {part.strip() for part in selection.split(",") if part.strip()}
    known = {key for request in requests for key in (request.image.target, request.image.target.split(":", 1)[0])}
    if not requested or requested - known:
        raise ValueError("unknown or empty ACR target selection")
    return [request for request in requests if requested.intersection(
        (request.image.target, request.image.target.split(":", 1)[0]))]


def plan(github: GitHub, event_name: str, event: dict, selection: str = "") -> list[SyncRequest]:
    if event_name == "workflow_run":
        return [to_request(completed_record(github, int(event["workflow_run"]["id"])))]
    if event_name not in {"push", "schedule", "workflow_dispatch"}:
        raise ValueError("unsupported ACR trigger")
    requests = external_requests() + [to_request(record) for record in load_imports()]
    if event_name != "push":
        requests.extend(to_request(record) for record in published_records(github))
    return select_requests(requests, selection)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate local intents without credentials or network")
    args = parser.parse_args()
    if args.check:
        requests = select_requests(external_requests() + [to_request(record) for record in load_imports()])
        print(f"Validated {len(requests)} external and imported delivery intents")
        return 0
    catalog = load_catalog()
    if os.environ["GITHUB_REPOSITORY"] != catalog["source_repository"] or os.environ["GITHUB_REF"] != "refs/heads/master":
        raise ValueError("ACR delivery requires the canonical default branch")
    event = json.loads(pathlib.Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    requests = plan(GitHub(catalog["source_repository"]), os.environ["GITHUB_EVENT_NAME"], event,
                    os.environ.get("MIRROR_IMAGES", ""))
    return run_requests(requests, status_only=os.environ.get("MIRROR_STATUS_ONLY") == "true",
                        report_path=pathlib.Path(os.environ["RUNNER_TEMP"]) / "acr-results.json")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
        message = str(error)
        for name in (*SECRET_NAMES, "GH_TOKEN", "GITHUB_TOKEN"):
            if value := os.environ.get(name):
                message = message.replace(value, "***")
        print(f"ACR delivery failed: {message}", file=sys.stderr)
        sys.exit(1)
