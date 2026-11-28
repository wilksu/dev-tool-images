#!/usr/bin/env python3
"""Build one toolchain with the arguments in its inventory."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from image_config import build_arguments


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
    command = ["docker", "buildx", "build", "--platform", inventory["platform"],
               "--progress=plain", "--provenance=false"]
    if args.tag:
        command.extend(["--load", "--tag", args.tag])
    if args.oci:
        command.extend(["--output", f"type=oci,tar=false,dest={args.oci}"])
    if args.revision:
        command.extend(["--label", f"org.opencontainers.image.revision={args.revision}"])
    for value in build_arguments(inventory):
        command.extend(["--build-arg", value])

    with tempfile.TemporaryDirectory() as context:
        (Path(context) / "image.json").write_text(inventory_path.read_text())
        subprocess.run([*command, "--build-context", f"inventory={context}",
                        str(image_dir)], check=True)


if __name__ == "__main__":
    main()
