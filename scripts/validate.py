#!/usr/bin/env python3
"""Validate public contracts and the boundaries between their authorities."""

from __future__ import annotations

import pathlib
import re

from jsonschema import Draft202012Validator, FormatChecker

from image_config import RUNNERS, build_arguments, load_catalog, load_image, read_json
from resolve_release import resolve_release


ROOT = pathlib.Path(__file__).resolve().parents[1]
DIGEST_REFERENCE = re.compile(r"@sha256:[0-9a-f]{64}$")
ACTION_COMMIT = re.compile(r"[0-9a-f]{40}")


def validate_npm(config: dict, image_dir: pathlib.Path) -> None:
    package = read_json(image_dir / "package.json")
    lock = read_json(image_dir / config["npm_lock"])
    declared: dict[str, tuple[str, str]] = {}
    for group in ("dependencies", "devDependencies"):
        dependencies = package.get(group, {})
        assert lock["packages"][""].get(group, {}) == dependencies
        declared.update((name, (version, group)) for name, version in dependencies.items())
    inventoried = {
        component["package"]: (
            component["version"],
            component["manifest"].split("#", 1)[1],
        )
        for component in config["inventory"]["components"]
        if component["kind"] == "npm-package"
    }
    assert inventoried == declared


def validate_image(
    name: str, entry: dict, catalog: dict, inventory_validator: Draft202012Validator
) -> None:
    assert entry == {
        "registry": f"ghcr.io/wilksu/dev-tool-images/{name}",
        "config": f"images/{name}/image.json",
        "inventory": f"images/{name}/image.json#inventory",
        "fixture": entry["fixture"],
        "release_tag_prefix": f"{name}/rev-",
        "discovery_tag_prefix": "sha-",
    }
    assert (ROOT / entry["fixture"]).is_dir()

    _, config = load_image(name, catalog)
    assert config["schema"] == 3
    assert config["name"] == name
    assert all(DIGEST_REFERENCE.search(value) for value in config["base_images"].values())
    inventory_validator.validate(config["inventory"])
    components = config["inventory"]["components"]
    assert len({component["id"] for component in components}) == len(components)
    for component in components:
        if component["kind"] == "release-binary":
            assert {item["platform"] for item in component["artifacts"]} == set(
                catalog["platforms"]
            )

    image_dir = ROOT / entry["config"].rsplit("/", 1)[0]
    validate_npm(config, image_dir)
    dockerfile = (image_dir / "Dockerfile").read_text(encoding="utf-8")
    configured_args = {item.split("=", 1)[0] for item in build_arguments(config)}
    for argument in configured_args:
        assert re.search(rf"^ARG {re.escape(argument)}(?:=|$)", dockerfile, re.MULTILINE)
        assert f"${{{argument}}}" in dockerfile
    assert "org.opencontainers.image.version" not in dockerfile
    assert "org.opencontainers.image.revision" not in dockerfile
    assert "io.starferry.tool." not in dockerfile

    by_id = {component["id"]: component for component in components}
    if "go_base_image" in config["base_images"]:
        assert f"golang:{by_id['go']['version']}-" in config["base_images"]["go_base_image"]
    assert f"node:{by_id['node']['version']}-" in config["base_images"]["node_base_image"]
    verifier = image_dir / config["verifier"]
    assert verifier.is_file() and verifier.stat().st_mode & 0o111


def validate_workflows() -> None:
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    buildkit_images = set()
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for line in text.splitlines():
            if match := re.search(r"\buses:\s*[^@\s]+@([^\s#]+)", line):
                assert ACTION_COMMIT.fullmatch(match.group(1)), line
            if match := re.search(r"BUILDKIT_IMAGE:\s*(moby/buildkit@sha256:[0-9a-f]{64})", line):
                buildkit_images.add(match.group(1))
        if "docker/setup-buildx-action@" in text:
            assert "image=${{ env.BUILDKIT_IMAGE }}" in text
    assert len(buildkit_images) == 1

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "python3 scripts/image_config.py ci-matrix" in ci
    assert "scripts/verify_image.sh" in ci
    publish = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "- '*/rev-*'" in publish
    assert "python3 scripts/resolve_release.py" in publish
    assert "scripts/verify_manifest.py" in publish
    assert "org.opencontainers.image.version" not in publish


def main() -> None:
    catalog = load_catalog()
    assert catalog["schema"] == 2
    assert catalog["source_repository"] == "wilksu/dev-tool-images"
    assert catalog["identity"] == {
        "release": "source_revision",
        "discovery": "source_revision_tag",
        "consumer": "oci_manifest_digest",
        "source_revision_pattern": "^[0-9a-f]{40}$",
    }
    assert catalog["platforms"] == ["linux/amd64", "linux/arm64"]
    assert set(RUNNERS) == set(catalog["platforms"])
    assert set(catalog["images"]) == {"go-contract-tools", "playwright-client-tools"}

    schema = read_json(ROOT / catalog["inventory_schema"])
    Draft202012Validator.check_schema(schema)
    inventory_validator = Draft202012Validator(schema, format_checker=FormatChecker())
    revision = "a" * 40
    for name, entry in catalog["images"].items():
        validate_image(name, entry, catalog, inventory_validator)
        release, _ = resolve_release(f"{entry['release_tag_prefix']}{revision}", revision)
        assert release["image_name"] == name
        assert release["platforms"] == ",".join(catalog["platforms"])
        try:
            resolve_release(f"{entry['release_tag_prefix']}{revision}", "b" * 40)
        except ValueError as error:
            assert "does not match checked-out commit" in str(error)
        else:
            raise AssertionError("revision mismatch was accepted")
    validate_workflows()


if __name__ == "__main__":
    main()
