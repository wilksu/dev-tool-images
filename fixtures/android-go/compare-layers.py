#!/usr/bin/env python3
"""Check component reuse and count the exact missing compressed layer bytes."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def manifest(layout):
    index = json.loads((layout / "index.json").read_text())
    descriptor, = index["manifests"]
    while "index" in descriptor["mediaType"]:
        algorithm, digest = descriptor["digest"].split(":", 1)
        nested = json.loads((layout / "blobs" / algorithm / digest).read_text())
        descriptor, = nested["manifests"]
    algorithm, digest = descriptor["digest"].split(":", 1)
    return descriptor["digest"], json.loads((layout / "blobs" / algorithm / digest).read_text())


def main():
    build = Path(sys.argv[1]).resolve()
    config = json.loads(build.with_name("image.json").read_text())
    baseline_digest, baseline_manifest = manifest(Path(sys.argv[2]))
    baseline = baseline_manifest["layers"]
    print(f"Baseline OCI manifest: {baseline_digest}", flush=True)
    print(f"Baseline compressed layer bytes: {sum(layer['size'] for layer in baseline)}", flush=True)
    baseline_digests = {layer["digest"] for layer in baseline}
    variations = {
        "go": {"version": "1.27.3",
               "url": "https://go.dev/dl/go1.27.3.linux-amd64.tar.gz",
               "sha256": "65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40"},
        "android_platform": {"package": "platforms;android-37.1", "revision": "1", "url":
                             "https://dl.google.com/android/repository/platform-37.1_r01.zip",
                             "sha1": "62aeba1ec09c2b1fdf888e79549daf678fa0d75f"},
    }
    for component, replacement in variations.items():
        with tempfile.TemporaryDirectory() as tmp:
            variant = copy.deepcopy(config)
            variant[component] = replacement
            inventory = Path(tmp) / "image.json"
            inventory.write_text(json.dumps(variant, indent=2) + "\n")
            oci = Path(tmp) / "oci"
            subprocess.run([sys.executable, str(build), "--config", str(inventory),
                            "--oci", str(oci)], check=True)
            _, variant_manifest = manifest(oci)
            changed = variant_manifest["layers"]
            component_offset = -2 if component == "go" else -3
            assert len(changed) == len(baseline)
            for index, (old, new) in enumerate(zip(baseline, changed)):
                expected_change = index in (len(baseline) - 1, len(baseline) + component_offset)
                assert (old["digest"] != new["digest"]) == expected_change, (component, index)
            missing_bytes = sum(layer["size"] for layer in changed
                                if layer["digest"] not in baseline_digests)
            print(f"{component}: unchanged NDK {changed[-5]['digest']}", flush=True)
            print(f"{component}: compressed bytes absent from the baseline {missing_bytes}", flush=True)


if __name__ == "__main__":
    main()
