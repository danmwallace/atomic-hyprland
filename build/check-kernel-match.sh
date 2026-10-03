#!/usr/bin/bash
# Fail unless the base image and the NVIDIA akmods image were built for the
# same kernel. Both ublue images carry the kernel in the ostree.linux label.
# Usage: check-kernel-match.sh [BASE_IMAGE] [AKMODS_IMAGE]  (defaults: build/images.env)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=images.env
source "${here}/images.env"
base="${1:-${BASE_IMAGE}}"
akmods="${2:-${AKMODS_IMAGE}}"

# skopeo refuses "name:tag@sha256:..." (podman/buildah accept it); drop the tag.
skopeo_ref() {
    sed -E 's#:[^:/@]+@sha256:#@sha256:#' <<< "$1"
}

kernel_of() {
    skopeo inspect --no-tags "docker://$(skopeo_ref "$1")" | jq -r '.Labels["ostree.linux"] // empty'
}

base_kernel="$(kernel_of "${base}")"
akmods_kernel="$(kernel_of "${akmods}")"

if [[ -z "${base_kernel}" || -z "${akmods_kernel}" ]]; then
    echo "check-kernel: could not read ostree.linux label (base='${base_kernel}' akmods='${akmods_kernel}')" >&2
    exit 2
fi
if [[ "${base_kernel}" != "${akmods_kernel}" ]]; then
    echo "check-kernel: MISMATCH base=${base_kernel} akmods=${akmods_kernel}" >&2
    exit 1
fi
echo "check-kernel: ok ${base_kernel}"
