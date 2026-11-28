#!/usr/bin/env bash
set -euo pipefail
# Do not let unrelated vendor repositories on hosted runners block delivery.
apt_options=(-o Dir::Etc::sourcelist=/etc/apt/sources.list.d/ubuntu.sources
  -o Dir::Etc::sourceparts=- -o Acquire::Retries=3)
sudo apt-get "${apt_options[@]}" update -qq
sudo apt-get "${apt_options[@]}" install -y --no-install-recommends skopeo
