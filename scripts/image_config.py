#!/usr/bin/env python3
"""Read the public catalog and project image configurations."""

from __future__ import annotations

import argparse
import json
import os
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNERS = {
    "linux/amd64": "ubuntu-24.04",
    "linux/arm64": "ubuntu-24.04-arm",
}


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog() -> dict:
    return read_json(ROOT / "catalog/v1/images.json")


def load_image(name: str, catalog: dict | None = None) -> tuple[dict, dict]:
    catalog = catalog or load_catalog()
    try:
        entry = catalog["images"][name]
    except KeyError as error:
        raise ValueError(f"unknown image: {name}") from error
    return entry, read_json(ROOT / entry["config"])


def build_arguments(config: dict) -> list[str]:
    arguments: dict[str, str] = {}

    def add(key: str, value: str) -> None:
        if key in arguments:
            raise ValueError(f"duplicate build argument: {key}")
        arguments[key] = value

    for key, value in config["base_images"].items():
        add(key.upper(), value)
    for component in config["inventory"]["components"]:
        if key := component.get("version_arg"):
            add(key, component["version"])
        if key := component.get("source_revision_arg"):
            add(key, component["source_revision"])
        for dependency in component.get("build_dependencies", []):
            add(dependency["source_revision_arg"], dependency["source_revision"])
        for artifact in component.get("artifacts", []):
            add(artifact["sha256_arg"], artifact["sha256"])
    return [f"{key}={value}" for key, value in arguments.items()]


def ci_matrix(catalog: dict) -> dict[str, list[dict[str, str]]]:
    include = []
    for name, entry in catalog["images"].items():
        for platform in catalog["platforms"]:
            include.append(
                {
                    "image": name,
                    "fixture": entry["fixture"],
                    "arch": platform.rsplit("/", 1)[1],
                    "platform": platform,
                    "runner": RUNNERS[platform],
                }
            )
    return {"include": include}


def write_github_output(key: str, value: str) -> None:
    output_path = pathlib.Path(os.environ["GITHUB_OUTPUT"])
    with output_path.open("a", encoding="utf-8") as output:
        if "\n" in value:
            output.write(f"{key}<<{key.upper()}\n{value}\n{key.upper()}\n")
        else:
            output.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_args = subparsers.add_parser("build-args")
    build_args.add_argument("image")
    fixture = subparsers.add_parser("fixture")
    fixture.add_argument("image")
    subparsers.add_parser("ci-matrix")
    args = parser.parse_args()

    catalog = load_catalog()
    if args.command == "build-args":
        _, config = load_image(args.image, catalog)
        value = "\n".join(build_arguments(config))
        if "GITHUB_OUTPUT" in os.environ:
            write_github_output("build_args", value)
        else:
            print(value)
    elif args.command == "fixture":
        entry, _ = load_image(args.image, catalog)
        print(entry["fixture"])
    elif args.command == "ci-matrix":
        value = json.dumps(ci_matrix(catalog), separators=(",", ":"))
        if "GITHUB_OUTPUT" in os.environ:
            write_github_output("matrix", value)
        else:
            print(value)


if __name__ == "__main__":
    main()
