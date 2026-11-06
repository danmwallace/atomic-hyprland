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

exit "$fail"
