#!/usr/bin/bash
# Host-side: bash tests/test-justfile.sh (run from the repo root)
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

# CI sets IMAGE_VERSION; the justfile must use it verbatim.
check test "$(IMAGE_VERSION=20261005-abc1234 just --evaluate version)" = 20261005-abc1234
# Locally the computed version still has the date-sha shape.
check bash -c 'just --evaluate version | grep -Eq "^[0-9]{8}-[0-9a-f]{7,}(-dirty)?$"'
# CI is the only publisher.
check bash -c '! just --summary | grep -qw push'
check bash -c 'just --summary | grep -qw sign'
# An empty key must fail before any network call, with a clear message.
check bash -c 'COSIGN_PRIVATE_KEY= just sign 2>&1 | grep -q "COSIGN_PRIVATE_KEY is not set"'
check bash -c '! COSIGN_PRIVATE_KEY= just sign >/dev/null 2>&1'
# The recipe signs by digest with the legacy flags bootc can verify.
check bash -c 'just -n sign 2>&1 | grep -q -- "--new-bundle-format=false --use-signing-config=false"'
check bash -c 'just -n sign 2>&1 | grep -q "env://COSIGN_PRIVATE_KEY"'
check bash -c 'just -n sign 2>&1 | grep -q "cosign verify --new-bundle-format=false --key cosign.pub"'
check bash -c 'just -n sign dev-x 2>&1 | grep -q "docker://ghcr.io/danmwallace/atomic-hyprland:dev-x"'

# Phase 4: one image, always with the NVIDIA layer; just supplies the akmods ref.
check bash -c 'just -n build 2>&1 | grep -q -- "--build-arg AKMODS_IMAGE="'
check bash -c '! just -n build 2>&1 | grep -q "NVIDIA="'
check bash -c '! just --show build | head -3 | grep -q nvidia='

# The image ships every theme; there is no THEME build argument any more.
check bash -c '! just --show build | grep -q THEME'
check bash -c '! grep -q THEME Containerfile'

# Installer ISO for bare metal: an interactive Anaconda install (the user picks the disk,
# sets the LUKS passphrase and creates the user). BIB is unattended (zerombr/clearpart/
# autopart, wipes the first disk) only when a config asks for it; nothing here may.
check bash -c 'just --show iso | grep -q -- "--type anaconda-iso"'
check bash -c 'just --show iso | grep -q -- "--rootfs btrfs"'
check bash -c 'just --show iso | grep -q "output/bootiso/install.iso"'
check bash -c '! just --show iso | grep -qi unattended'
check bash -c 'just --show iso | grep -q -- "-v ./build/iso.toml:/config.toml:ro"'
check bash -c 'just --show iso | grep -q "bash tests/test-iso.sh output/bootiso/install.iso"'
check bash -c '! cat build/*.toml | grep -vE "^\s*#" | grep -qiE "unattended|clearpart|zerombr|autopart"'

exit "$fail"
