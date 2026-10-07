#!/usr/bin/env bash
# Install the system libraries Qt needs on an Ubuntu CI runner.
#
# The runners' default mirror (azure.archive.ubuntu.com) sometimes stops
# answering, and apt then waits on it with no output until the job is
# killed.  So use Ubuntu's own archive instead, give each attempt a hard time
# limit, and try a few times.
set -euo pipefail

for file in /etc/apt/sources.list /etc/apt/apt-mirrors.txt; do
    if [ -f "$file" ]; then
        sudo sed -i 's#http://azure.archive.ubuntu.com#http://archive.ubuntu.com#g' "$file"
    fi
done

apt=(sudo apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=20
     -o Acquire::https::Timeout=20)
packages=(libegl1 libfontconfig1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4
          libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0)

for attempt in 1 2 3; do
    if timeout 150 "${apt[@]}" update &&
       timeout 150 "${apt[@]}" install -y --no-install-recommends "${packages[@]}"; then
        exit 0
    fi
    echo "Installing the Qt libraries failed (attempt $attempt); trying again" >&2
    sleep 10
done
exit 1
