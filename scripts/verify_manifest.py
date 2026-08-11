#!/usr/bin/env python3
"""Verify a published GHCR manifest through anonymous registry access."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--platforms", required=True)
    args = parser.parse_args()

    if not args.image.startswith("ghcr.io/"):
        raise SystemExit(f"unsupported registry: {args.image}")
    repository = args.image.removeprefix("ghcr.io/")
    query = urllib.parse.urlencode({"scope": f"repository:{repository}:pull"})
    with urllib.request.urlopen(f"https://ghcr.io/token?{query}", timeout=30) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{repository}/manifests/sha-{args.revision}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": (
                "application/vnd.oci.image.index.v1+json,"
                "application/vnd.docker.distribution.manifest.list.v2+json"
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        header_digest = response.headers.get("Docker-Content-Digest")
    computed_digest = "sha256:" + hashlib.sha256(body).hexdigest()
    if computed_digest != args.digest:
        raise SystemExit(
            f"anonymous manifest digest mismatch: expected {args.digest}, "
            f"got {computed_digest}"
        )
    if header_digest and header_digest != args.digest:
        raise SystemExit(
            f"registry digest mismatch: expected {args.digest}, got {header_digest}"
        )
    published = {
        f"{platform.get('os', '')}/{platform.get('architecture', '')}"
        for item in json.loads(body).get("manifests", [])
        if (platform := item.get("platform") or {})
    }
    required = set(args.platforms.split(","))
    if not required.issubset(published):
        raise SystemExit(f"published manifest is missing platforms: {required - published}")
    print(
        json.dumps(
            {"anonymous": True, "digest": args.digest, "platforms": sorted(required)},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
