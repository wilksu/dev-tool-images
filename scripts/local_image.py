#!/usr/bin/env python3
"""Local build and fixture entry point; never publish to a registry."""

import argparse
import os
import subprocess
import tempfile

from image_config import ROOT, build_arguments, load_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "verify"))
    parser.add_argument("--image", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    entry, config = load_image(args.image)
    if args.operation == "build":
        command = ["docker", "buildx", "build", "--load", "--tag", args.tag]
        for value in build_arguments(config):
            command.extend(["--build-arg", value])
        if entry["driver"] == "android":
            command.extend(["--platform", entry["platforms"][0], "--build-context", f"inventory={ROOT / 'images' / args.image}"])
        subprocess.run([*command, str(ROOT / "images" / args.image)], check=True)
    elif entry["driver"] == "android":
        with tempfile.TemporaryDirectory(prefix="android-verify-") as directory:
            subprocess.run(["bash", str(ROOT / "scripts/verify_android_image.sh"), args.tag], cwd=ROOT,
                           env={**os.environ, "RUNNER_TEMP": directory}, check=True)
    else:
        subprocess.run([str(ROOT / "scripts/verify_image.sh"), args.tag, entry["fixture"]], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
