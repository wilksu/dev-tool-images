#!/usr/bin/env python3
"""Plan image verification from repository changes; never perform registry writes."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import pathlib
import re
import subprocess

from image_config import ci_matrix, load_catalog, write_github_output


def documentation(path: str) -> bool:
    return (path in {"README.md", "SECURITY.md", "THIRD_PARTY.md", "LICENSE"}
            or path.startswith("docs/")
            or (path.startswith("images/") and path.endswith("/README.md")))


def plan_changes(paths: list[str], catalog: dict | None = None) -> dict:
    catalog = catalog or load_catalog()
    inputs = [path for path in paths if not documentation(path)]
    shared = any(fnmatch.fnmatchcase(path, pattern)
                 for path in inputs for pattern in catalog["shared_build_inputs"])
    selected = [name for name, entry in catalog["images"].items()
                if shared or any(fnmatch.fnmatchcase(path, pattern)
                                 for path in inputs for pattern in entry["inputs"])]
    return {"images": selected, "build": bool(selected), "matrix": ci_matrix(catalog, selected)}


def changed_paths(event_name: str, event: dict) -> list[str]:
    if event_name == "pull_request":
        before, after = event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"]
        separator = "..."
    elif event_name == "push":
        before, after = event["before"], event["after"]
        separator = ".."
    else:
        raise ValueError(f"unsupported change event: {event_name}")
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (before, after)):
        raise ValueError("invalid change boundary")
    # Disabling rename detection includes both old and new names, covering
    # deletion and moves between image ownership boundaries.
    command = (["git", "ls-tree", "-r", "--name-only", "-z", after] if before == "0" * 40 else
               ["git", "diff", "--name-only", "--no-renames", "-z", f"{before}{separator}{after}"])
    raw = subprocess.run(command, check=True, stdout=subprocess.PIPE).stdout
    return [path.decode("utf-8") for path in raw.split(b"\0") if path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", nargs="*", help="explicit paths for local planning")
    args = parser.parse_args()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event = json.loads(pathlib.Path(os.environ["GITHUB_EVENT_PATH"]).read_text()) if args.paths is None else {}
    if event_name == "workflow_dispatch" and args.paths is None:
        catalog = load_catalog()
        requested = event.get("inputs", {}).get("images", "all") or "all"
        names = list(catalog["images"]) if requested == "all" else list(dict.fromkeys(requested.split(",")))
        if not names or any(name not in catalog["images"] for name in names):
            raise ValueError("unknown image selection")
        result = {"images": names, "build": True, "matrix": ci_matrix(catalog, names)}
    else:
        result = plan_changes(args.paths if args.paths is not None else changed_paths(event_name, event))
    if "GITHUB_OUTPUT" in os.environ:
        write_github_output("build", str(result["build"]).lower())
        write_github_output("matrix", json.dumps(result["matrix"], separators=(",", ":")))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
