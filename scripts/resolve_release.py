#!/usr/bin/env python3
"""Resolve one revision release tag through the checked-in public catalog."""

from __future__ import annotations

import json
import os
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]


def resolve_release(tag: str, checked_revision: str) -> tuple[dict[str, str], list[str]]:
    catalog = json.loads(
        (ROOT / "catalog/v1/images.json").read_text(encoding="utf-8")
    )
    if catalog["identity"]["release"] != "source_revision":
        raise ValueError("catalog is not revision-centric")
    selected = [
        (name, entry)
        for name, entry in catalog["images"].items()
        if tag.startswith(entry["release_tag_prefix"])
    ]
    if len(selected) != 1:
        raise ValueError(f"tag selects {len(selected)} images, expected exactly one")
    name, entry = selected[0]
    revision = tag.removeprefix(entry["release_tag_prefix"])
    pattern = catalog["identity"]["source_revision_pattern"]
    if not re.fullmatch(pattern, revision):
        raise ValueError(f"invalid source revision: {revision}")
    if revision != checked_revision:
        raise ValueError(
            f"tag revision {revision} does not match checked-out commit "
            f"{checked_revision}"
        )

    config_path = ROOT / entry["config"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config["name"] != name:
        raise ValueError("catalog and image configuration disagree")
    if config["platforms"] != ["linux/amd64", "linux/arm64"]:
        raise ValueError("release platform contract is not the required pair")

    arguments = [
        f"{key.upper()}={value}"
        for section in ("base_images", "tools", "packages")
        for key, value in config.get(section, {}).items()
    ]
    arguments.append(f"SOURCE_REVISION={revision}")
    outputs = {
        "image_name": name,
        "image": entry["registry"],
        "revision": revision,
        "discovery_tag": (
            f"{entry['registry']}:"
            f"{entry['discovery_tag_prefix']}{revision}"
        ),
        "inventory_path": entry["inventory"],
        "context": str(config_path.parent.relative_to(ROOT)),
    }
    return outputs, arguments


def main() -> None:
    outputs, arguments = resolve_release(
        os.environ["RELEASE_TAG"], os.environ["SOURCE_REVISION"]
    )
    output_path = pathlib.Path(os.environ["GITHUB_OUTPUT"])
    with output_path.open("a", encoding="utf-8") as output:
        for key, value in outputs.items():
            output.write(f"{key}={value}\n")
        output.write("build_args<<BUILD_ARGS\n")
        output.write("\n".join(arguments))
        output.write("\nBUILD_ARGS\n")


if __name__ == "__main__":
    main()
