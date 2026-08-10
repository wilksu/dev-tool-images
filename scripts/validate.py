#!/usr/bin/env python3
"""Validate the repository's public machine contracts without dependencies."""

from __future__ import annotations

import json
import pathlib
import re

from resolve_release import resolve_release


ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE_NAMES = {"go-contract-tools", "playwright-client-tools"}
REQUIRED_PLATFORMS = ["linux/amd64", "linux/arm64"]
BUILDKIT_IMAGE = (
    "moby/buildkit@sha256:"
    "2f5adac4ecd194d9f8c10b7b5d7bceb5186853db1b26e5abd3a657af0b7e26ec"
)
DIGEST_REFERENCE = re.compile(r"@sha256:[0-9a-f]{64}$")
ACTION_COMMIT = re.compile(r"[0-9a-f]{40}")
COMPONENT_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)+(?:[-+][0-9A-Za-z.-]+)?$")


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_version(config: dict, key: str) -> str:
    section, name = key.split(".", 1)
    value = config[section][name]
    return value.removeprefix("v")


def validate_image(name: str, entry: dict) -> None:
    assert entry["registry"] == f"ghcr.io/wilksu/dev-tool-images/{name}"
    assert entry["release_tag_prefix"] == f"{name}/rev-"
    assert entry["discovery_tag_prefix"] == "sha-"
    assert entry["inventory"] == f"images/{name}/image.json#inventory"

    config_path = ROOT / entry["config"]
    config = read_json(config_path)
    assert config["schema"] == 2
    assert config["name"] == name
    assert config["platforms"] == REQUIRED_PLATFORMS
    assert all(DIGEST_REFERENCE.search(value) for value in config["base_images"].values())

    inventory = config["inventory"]
    assert inventory["schema"] == 1
    assert inventory["scope"] == "direct"
    assert inventory["transitive_inventory"] == "published-sbom"
    components = inventory["components"]
    assert components
    assert len({component["id"] for component in components}) == len(components)

    configured_keys = {
        f"{section}.{key}"
        for section in ("tools", "packages")
        for key in config.get(section, {})
    }
    claimed_keys: set[str] = set()
    npm_inventory: dict[str, tuple[str, str]] = {}
    alpine_inventory: dict[str, str] = {}
    go_install_inventory: dict[str, str] = {}

    for component in components:
        assert set(component) >= {"id", "kind", "package", "version", "source"}
        assert component["kind"] in {"runtime", "go-module", "npm-package", "alpine-package"}
        assert COMPONENT_VERSION.fullmatch(component["version"]), component
        assert component["source"].startswith("https://")
        if "executables" in component:
            assert component["executables"]
            assert len(set(component["executables"])) == len(component["executables"])

        version_key = component.get("version_key")
        if version_key:
            assert version_key in configured_keys
            assert version_key not in claimed_keys
            assert component["version"] == resolve_version(config, version_key)
            claimed_keys.add(version_key)

        if component["kind"] == "npm-package":
            manifest = component.get("manifest", "")
            manifest_file, group = manifest.split("#", 1)
            assert manifest_file == "package.json"
            assert group in {"dependencies", "devDependencies"}
            npm_inventory[component["package"]] = (component["version"], group)
        if component["kind"] == "go-module":
            assert version_key and version_key.startswith("tools.")
            go_install_inventory[component["install_target"]] = version_key.split(".", 1)[1].upper()
        if component["kind"] == "alpine-package":
            assert version_key and version_key.startswith("packages.alpine_")
            alpine_inventory[component["package"]] = component["version"]

    assert claimed_keys == configured_keys

    image_dir = config_path.parent
    package = read_json(image_dir / "package.json")
    lock = read_json(image_dir / config["npm_lock"])
    declared_npm: dict[str, tuple[str, str]] = {}
    for group in ("dependencies", "devDependencies"):
        declared = package.get(group, {})
        assert lock["packages"][""].get(group, {}) == declared
        declared_npm.update((dependency, (version, group)) for dependency, version in declared.items())
    assert npm_inventory == declared_npm

    dockerfile = (image_dir / "Dockerfile").read_text(encoding="utf-8")
    assert "org.opencontainers.image.version" not in dockerfile
    assert "IMAGE_VERSION" not in dockerfile
    for section in ("base_images", "tools", "packages"):
        for key in config.get(section, {}):
            assert re.search(rf"^ARG {re.escape(key.upper())}(?:=|$)", dockerfile, re.MULTILINE)
    expected_apk_entries = set()
    for package_name in alpine_inventory:
        key = next(
            key
            for key in config["packages"]
            if key == f"alpine_{package_name.replace('-', '_')}_version"
        )
        expected_apk_entries.add(f'"{package_name}=${{{key.upper()}}}"')
    if expected_apk_entries:
        apk_block = dockerfile.split("RUN apk add --no-cache \\\n", 1)[1].split("\n\n", 1)[0]
        apk_entries = {
            line.strip().removesuffix("\\").strip()
            for line in apk_block.splitlines()
            if line.strip()
        }
        assert apk_entries == expected_apk_entries

    go_installs = dict(
        re.findall(r'go install "([^"@]+)@\$\{([A-Z0-9_]+)\}"', dockerfile)
    )
    assert go_installs == go_install_inventory

    node = next(component for component in components if component["id"] == "node")
    assert f"node:{node['version']}-" in config["base_images"]["node_base_image"]
    if name == "go-contract-tools":
        go = next(component for component in components if component["id"] == "go")
        assert f"golang:{go['version']}-" in config["base_images"]["go_base_image"]

    verifier = image_dir / config["verifier"]
    assert verifier.is_file()
    assert verifier.stat().st_mode & 0o111


def validate_workflows() -> None:
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for line in text.splitlines():
            match = re.search(r"\buses:\s*[^@\s]+@([^\s#]+)", line)
            if match:
                assert ACTION_COMMIT.fullmatch(match.group(1)), line
        if "docker/setup-buildx-action@" in text:
            assert f"BUILDKIT_IMAGE: {BUILDKIT_IMAGE}" in text
            assert "image=${{ env.BUILDKIT_IMAGE }}" in text
    publish = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "docker/metadata-action@" not in publish
    assert "org.opencontainers.image.version" not in publish
    assert "IMAGE_VERSION" not in publish
    assert "run: python3 scripts/resolve_release.py" in publish
    assert "Verify published manifest anonymously" in publish
    resolver = (ROOT / "scripts/resolve_release.py").read_text(encoding="utf-8")
    assert "discovery_tag_prefix" in resolver
    assert "release_tag_prefix" in resolver


def main() -> None:
    catalog = read_json(ROOT / "catalog/v1/images.json")
    assert catalog["schema"] == 2
    assert catalog["source_repository"] == "wilksu/dev-tool-images"
    assert catalog["identity"] == {
        "release": "source_revision",
        "discovery": "source_revision_tag",
        "consumer": "oci_manifest_digest",
        "source_revision_pattern": "^[0-9a-f]{40}$",
    }
    assert catalog["inventory_schema"] == "catalog/v1/inventory.schema.json"
    schema = read_json(ROOT / catalog["inventory_schema"])
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema"]["const"] == 1
    assert set(catalog["images"]) == IMAGE_NAMES
    for name, entry in catalog["images"].items():
        validate_image(name, entry)
        revision = "a" * 40
        release, _ = resolve_release(
            f"{entry['release_tag_prefix']}{revision}", revision
        )
        assert release["image_name"] == name
        assert release["revision"] == revision
        assert release["discovery_tag"] == (
            f"{entry['registry']}:{entry['discovery_tag_prefix']}{revision}"
        )
        try:
            resolve_release(
                f"{entry['release_tag_prefix']}{revision}", "b" * 40
            )
        except ValueError as error:
            assert "does not match checked-out commit" in str(error)
        else:
            raise AssertionError("revision mismatch was accepted")
    validate_workflows()


if __name__ == "__main__":
    main()
