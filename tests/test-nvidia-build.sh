#!/usr/bin/bash
# Host-side: bash tests/test-nvidia-build.sh (repo root). Runs build/25-nvidia.sh
# inside the current local image against a fake akmods tree, so the kernel
# assertion is tested without a full build.
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

img=ghcr.io/danmwallace/atomic-hyprland:44
fake="$(mktemp -d)"; trap 'rm -rf "$fake"' EXIT
chmod 755 "$fake"
mkdir -p "$fake/kmods" "$fake/ublue-os"
printf 'KERNEL_VERSION=0.0.0-1.fc44.x86_64\nNVIDIA_AKMOD_VERSION=1-1\n' > "$fake/kmods/nvidia-vars"
printf '#!/bin/bash\necho INSTALLER-RAN\n' > "$fake/ublue-os/nvidia-install.sh"; chmod +x "$fake/ublue-os/nvidia-install.sh"
run() { podman run --rm -v ./build:/b:ro,Z -v "$fake":/tmp/akmods-rpms:ro,Z "$img" bash /b/25-nvidia.sh 2>&1; }
export -f run; export img fake

# A kmod built for another kernel must stop the build before the installer runs.
check bash -c '! run >/dev/null'
check bash -c 'run | grep -q "kernel mismatch: akmods built for 0.0.0-1.fc44.x86_64, image has "'
check bash -c '! run | grep -q INSTALLER-RAN'

exit "$fail"
