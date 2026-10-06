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

exit "$fail"
