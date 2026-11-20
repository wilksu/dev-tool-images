#!/bin/sh
set -eu

url=$1
sha1=$2
sha256=$3
package=$4
revision=$5
package_dir=$(printf '%s' "$package" | tr ';' '/')
destination="/out/$package_dir"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
cd "$scratch"
curl --fail --location --silent --show-error --retry 3 "$url" -o sdk.zip
echo "$sha1  sdk.zip" | sha1sum -c -
if [ -n "$sha256" ]; then
    echo "$sha256  sdk.zip" | sha256sum -c -
fi
printf '%s SHA-256 ' "$package"
sha256sum sdk.zip
unzip -q sdk.zip -d extracted

set -- extracted/*
test "$#" -eq 1
installed_revision=$(sed -n 's/^Pkg\.Revision[[:space:]]*=[[:space:]]*//p' "$1/source.properties" | tr -d '\r')
test "$installed_revision" = "$revision"
cp /opt/package.xml "$1/package.xml"
mkdir -p "$(dirname "$destination")"
mv "$1" "$destination"
