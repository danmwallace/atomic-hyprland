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

exit "$fail"
