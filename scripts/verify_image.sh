#!/bin/sh
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: $0 IMAGE FIXTURE [PLATFORM]" >&2
  exit 2
fi

image=$1
fixture=$2
platform=${3:-}
set --
if [ -n "$platform" ]; then
  set -- --platform "$platform"
fi

exec docker run --rm "$@" \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --mount "type=bind,src=${GITHUB_WORKSPACE:-$(pwd)},dst=/src,readonly" \
  "$image" verify-tool-image "/src/$fixture"
