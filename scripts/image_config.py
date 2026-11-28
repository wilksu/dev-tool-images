#!/usr/bin/env python3
"""Resolve owned image configuration and the compatible public v1 projection."""

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
    catalog = read_json(ROOT / "catalog/images.json")
    catalog["identity"] = {
        "release": "source_revision",
        "discovery": "source_revision_tag",
        "consumer": "oci_manifest_digest",
        "source_revision_pattern": "^[0-9a-f]{40}$",
    }
    for name, entry in catalog["images"].items():
        entry.update({
            "registry": f"ghcr.io/{catalog['source_repository']}/{name}",
            "config": f"images/{name}/image.json",
            "inventory": f"images/{name}/image.json" + ("#inventory" if entry["driver"] == "inventory" else ""),
            "release_tag_prefix": f"{name}/rev-",
            "discovery_tag_prefix": "sha-",
            "acr_repository": name,
        })
    return catalog


def legacy_catalog(catalog: dict | None = None) -> dict:
    catalog = catalog or load_catalog()
    names = catalog["legacy_v1_images"]
    platforms = catalog["images"][names[0]]["platforms"]
    if any(catalog["images"][name]["platforms"] != platforms for name in names):
        raise ValueError("public v1 cannot represent different platform sets; introduce a new API version")
    fields = ("registry", "config", "inventory", "fixture", "release_tag_prefix", "discovery_tag_prefix")
    return {
        "schema": 2,
        "source_repository": catalog["source_repository"],
        "identity": catalog["identity"],
        "inventory_schema": catalog["inventory_schema"],
        "platforms": platforms,
        "images": {name: {key: catalog["images"][name][key] for key in fields} for name in names},
    }


def load_image(name: str, catalog: dict | None = None) -> tuple[dict, dict]:
    catalog = catalog or load_catalog()
    try:
        entry = catalog["images"][name]
    except KeyError as error:
        raise ValueError(f"unknown image: {name}") from error
    return entry, read_json(ROOT / entry["config"])


def build_arguments(config: dict) -> list[str]:
    if "jdk" in config:
        arguments = {"JDK_BASE_IMAGE": config["jdk"]["image"]}
        for component in ("go", "android_platform", "build_tools", "ndk"):
            prefix = component.upper()
            for key in ("url", "sha256", "sha1", "package", "revision"):
                if key in config[component]:
                    arguments[f"{prefix}_{key.upper()}"] = config[component][key]
            if package := config[component].get("package"):
                arguments[f"{prefix}_METADATA"] = package.replace(";", "/") + ".xml"
        return [f"{key}={value}" for key, value in arguments.items()]
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


def ci_matrix(catalog: dict, names: list[str] | None = None) -> dict[str, list[dict[str, str]]]:
    include = []
    for name in names if names is not None else catalog["images"]:
        entry = catalog["images"][name]
        for platform in entry["platforms"]:
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
    subparsers.add_parser("legacy-catalog")
    args = parser.parse_args()

    catalog = load_catalog()
    if args.command == "build-args":
        entry, config = load_image(args.image, catalog)
        value = "\n".join(build_arguments(config))
        if "GITHUB_OUTPUT" in os.environ:
            write_github_output("build_args", value)
            write_github_output("build_contexts", f"inventory=images/{args.image}" if entry["driver"] == "android" else "")
            write_github_output("driver", entry["driver"])
            write_github_output("inventory_path", entry["inventory"])
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
    elif args.command == "legacy-catalog":
        print(json.dumps(legacy_catalog(catalog), indent=2))


if __name__ == "__main__":
    main()
