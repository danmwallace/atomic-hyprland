#!/usr/bin/bash
# Host-side: bash tests/test-build-pins.sh (repo root). Binaries fetched
# outside dnf must be verified against a hash pinned in this repo, not against
# a checksum file downloaded from the same place as the binary.
set -uo pipefail

fail=0
check() {
    if "$@" >/dev/null 2>&1; then
        echo "ok    $*"
    else
        echo "FAIL  $*"
        fail=1
    fi
}

check grep -Eq '^ARG TUIOS_SHA256=[0-9a-f]{64}$' Containerfile
check grep -q '"${TUIOS_SHA256}"' Containerfile
check grep -Fq 'echo "${tuios_sha256}  ${tuios_tar}" | sha256sum -c -' build/10-packages.sh
check bash -c '! grep -q "checksums.txt\"" build/10-packages.sh'

# JetBrainsMono Nerd Font: upstream release tarball, pinned by version and hash.
check grep -Eq '^ARG NERD_FONT_VERSION=[0-9]+\.[0-9]+\.[0-9]+$' Containerfile
check grep -Eq '^ARG NERD_FONT_SHA256=[0-9a-f]{64}$' Containerfile
check grep -q '"${NERD_FONT_VERSION}" "${NERD_FONT_SHA256}"' Containerfile
check grep -q 'releases/download/v${nerd_font_version}/' build/20-desktop.sh
check grep -q 'nerd_tar=JetBrainsMono.tar.xz' build/20-desktop.sh
check grep -Fq 'sha256sum -c -' build/20-desktop.sh
check bash -c '! grep -qE "SHA-256.txt|checksums.txt" build/20-desktop.sh'
check grep -q '/usr/share/fonts/jetbrains-mono-nerd' build/20-desktop.sh
check grep -q 'fc-cache' build/20-desktop.sh


# Orca (stablyai/orca, MIT): upstream RPM, pinned by version and hash, relocated out of /opt
check grep -Eq '^ARG ORCA_VERSION=[0-9]+\.[0-9]+\.[0-9]+$' Containerfile
check grep -Eq '^ARG ORCA_SHA256=[0-9a-f]{64}$' Containerfile
check grep -q 'releases/download/v${orca_version}/orca-ide-${orca_version}.x86_64.rpm' build/15-apps.sh
check grep -Fq 'echo "${orca_sha256}  ${orca_rpm}" | sha256sum -c -' build/15-apps.sh
check grep -q 'mv /opt/Orca /usr/lib/Orca' build/15-apps.sh
# spotify_player (aome510/spotify-player, MIT): upstream tarball, pinned by version and hash
check grep -Eq '^ARG SPOTIFY_PLAYER_VERSION=[0-9]+\.[0-9]+\.[0-9]+$' Containerfile
check grep -Eq '^ARG SPOTIFY_PLAYER_SHA256=[0-9a-f]{64}$' Containerfile
check grep -Fq 'echo "${spotify_player_sha256}  ${sp_tar}" | sha256sum -c -' build/15-apps.sh
# Tailscale: upstream repo with repo_gpgcheck, enabled only for the build
check grep -q 'pkgs.tailscale.com/stable/fedora/tailscale.repo' build/15-apps.sh
check grep -q 'tailscale-stable.enabled=0' build/90-cleanup.sh
# no self-referential checksums (a hash fetched from the same release)
check bash -c '! grep -qE "\.sha256\"|latest-linux.yml|checksums.txt" build/15-apps.sh'
for m in ORCA_VERSION SPOTIFY_PLAYER_VERSION; do
    check jq -e --arg m "$m" '.customManagers[] | select(.matchStrings[0] | test($m))' renovate.json
done

exit "$fail"
