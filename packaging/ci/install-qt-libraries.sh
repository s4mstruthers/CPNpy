#!/usr/bin/env bash
# Install the system libraries Qt needs on an Ubuntu CI runner.
#
# The runners' connection to Ubuntu's package mirrors is sometimes so slow
# that a few hundred kilobytes take minutes, or apt waits with no output
# until the job is killed.  So the packages (12 small .deb files) are kept in
# QT_DEBS (a folder the workflow caches between runs) and installed from
# there; the mirrors are only needed when that folder is empty or out of date.
set -uo pipefail

cache="${QT_DEBS:-$HOME/.cache/qt-debs}"
packages=(libegl1 libfontconfig1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4
          libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0)

installed() {        # every one of the packages, not just most of them
    local ok
    ok=$(dpkg-query -W -f='${Status}\n' "${packages[@]}" 2>/dev/null \
         | grep -c "install ok installed")
    [ "$ok" -eq "${#packages[@]}" ]
}

if installed; then
    echo "The Qt libraries are already installed."
    exit 0
fi

# 1. From the cache: no network at all.
if compgen -G "$cache/*.deb" > /dev/null; then
    echo "Installing the Qt libraries from the cache ($cache)."
    sudo dpkg -i --skip-same-version "$cache"/*.deb > /dev/null 2>&1
    if installed; then
        exit 0
    fi
    echo "The cached packages no longer fit this runner; downloading them again." >&2
    rm -rf "$cache"
fi

# 2. From Ubuntu's archive (not the runners' default mirror, which stalls),
#    keeping the downloaded files for the cache.
for file in /etc/apt/sources.list /etc/apt/apt-mirrors.txt; do
    [ -f "$file" ] && sudo sed -i 's#http://azure.archive.ubuntu.com#http://archive.ubuntu.com#g' "$file"
done
apt=(sudo apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30
     -o APT::Keep-Downloaded-Packages=true)
sudo rm -f /etc/apt/apt.conf.d/docker-clean        # would delete the downloaded files
# The runner's package lists are usually recent enough: try without updating
# them first (that alone downloads tens of megabytes).
"${apt[@]}" install -y --no-install-recommends "${packages[@]}" \
    || { "${apt[@]}" update && "${apt[@]}" install -y --no-install-recommends "${packages[@]}"; }
if ! installed; then
    echo "Could not install the Qt libraries." >&2
    exit 1
fi
mkdir -p "$cache"
cp /var/cache/apt/archives/*.deb "$cache"/ 2>/dev/null || true
echo "Kept $(ls "$cache" | wc -l) packages in the cache for the next run."
