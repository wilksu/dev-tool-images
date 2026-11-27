#!/usr/bin/env python3
"""Build one toolchain with the arguments in its inventory."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--oci", type=Path)
    parser.add_argument("--revision")
    args = parser.parse_args()
    if not (args.tag or args.oci):
        parser.error("choose --tag, --oci, or both")
    if args.revision and not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a full Git commit SHA")

    image_dir = Path(__file__).resolve().parent
    inventory_path = args.config or image_dir / "image.json"
    inventory = json.loads(inventory_path.read_text())
    inputs = {"JDK_BASE_IMAGE": inventory["jdk"]["image"]}
    for component in ("go", "android_platform", "build_tools", "ndk"):
        prefix = component.upper()
        for key in ("url", "sha256", "sha1", "package", "revision"):
            if key in inventory[component]:
                inputs[f"{prefix}_{key.upper()}"] = inventory[component][key]
        if package := inventory[component].get("package"):
            inputs[f"{prefix}_METADATA"] = package.replace(";", "/") + ".xml"

    command = ["docker", "buildx", "build", "--platform", inventory["platform"],
               "--progress=plain", "--provenance=false"]
    if args.tag:
        command.extend(["--load", "--tag", args.tag])
    if args.oci:
        command.extend(["--output", f"type=oci,tar=false,dest={args.oci}"])
    if args.revision:
        command.extend(["--label", f"org.opencontainers.image.revision={args.revision}"])
    for name, value in inputs.items():
        command.extend(["--build-arg", f"{name}={value}"])

    with tempfile.TemporaryDirectory() as context:
        (Path(context) / "image.json").write_text(inventory_path.read_text())
        subprocess.run([*command, "--build-context", f"inventory={context}",
                        str(image_dir)], check=True)


if __name__ == "__main__":
    main()
