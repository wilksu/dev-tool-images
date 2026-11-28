#!/usr/bin/env python3
"""Run fixtures against the exported candidate and emit a receipt only on success."""

import argparse
import json
import pathlib
import re
import subprocess

from image_config import ROOT, load_image
from oci_artifacts import root_digest, runtime_view, unpack, verify_candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--archive", type=pathlib.Path, required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--check-layers", action="store_true")
    args = parser.parse_args()
    entry, _ = load_image(args.image)
    if args.platform not in entry["platforms"] or not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ValueError("invalid candidate identity")
    archive = args.archive.resolve()
    layout = unpack(archive, archive.parent / "layout")
    root = root_digest(layout, args.digest)
    receipt = verify_candidate(layout, root, args.image, args.revision, args.platform)
    view = runtime_view(layout, root, args.platform, archive.parent / "runtime")
    image = f"dev-tool-images-verify/{args.image}:{args.revision}"
    subprocess.run(["skopeo", "copy", "--retry-times", "3", f"oci:{view}", f"docker-daemon:{image}"], check=True)
    config = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image], check=True,
                            stdout=subprocess.PIPE, text=True).stdout.strip()
    if config != receipt["config_digest"]:
        raise ValueError("loaded runtime differs from the exported candidate")
    if entry["driver"] == "android":
        subprocess.run(["bash", str(ROOT / "scripts/verify_android_image.sh"), image], check=True)
        if args.check_layers:
            subprocess.run(["python3", str(ROOT / "fixtures/android-go/compare-layers.py"),
                            str(ROOT / "images/android-go-tools/build.py"), str(layout)], check=True)
    else:
        subprocess.run([str(ROOT / "scripts/verify_image.sh"), image, entry["fixture"], args.platform],
                       cwd=ROOT, check=True)
    receipt["verified"] = True
    (archive.parent / "candidate.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
