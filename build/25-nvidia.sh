#!/usr/bin/bash
# NVIDIA driver layer. The RPMs and ublue's installer come from the pinned
# akmods image, bind-mounted at AKMODNV_PATH by the Containerfile.
set -euo pipefail
: "${AKMODNV_PATH:=/tmp/akmods-rpms}"

# check-kernel compares image labels before the build; this compares what is
# installed. A kmod for another kernel would install and then never load.
source "${AKMODNV_PATH}/kmods/nvidia-vars"
image_kernel="$(rpm -q --queryformat='%{evr}.%{arch}' kernel-core)"
if [ "${KERNEL_VERSION}" != "${image_kernel}" ]; then
    echo "kernel mismatch: akmods built for ${KERNEL_VERSION}, image has ${image_kernel}" >&2
    exit 1
fi

# The installer disables this repo and never restores it.
openh264_was_enabled=0
if dnf5 repolist --enabled | grep -q '^fedora-cisco-openh264'; then
    openh264_was_enabled=1
fi

IMAGE_NAME=base AKMODNV_PATH="${AKMODNV_PATH}" MULTILIB=0 "${AKMODNV_PATH}/ublue-os/nvidia-install.sh"

# It enables ublue-os/staging with `copr enable` but only overrides it off,
# leaving the repo file enabled=1. The COPR is transient (only while ublue has
# something staged), so disable it only when the file exists: `copr disable`
# fails on a repo that was never enabled.
staging_repo=/etc/yum.repos.d/_copr:copr.fedorainfracloud.org:ublue-os:staging.repo
if [ -f "${staging_repo}" ]; then
    dnf -y copr disable ublue-os/staging
fi
if [ "${openh264_was_enabled}" = 1 ]; then
    dnf5 config-manager setopt fedora-cisco-openh264.enabled=1
fi

# As Aurora does: no nouveau Vulkan ICD next to the NVIDIA one, and the
# unversioned libnvidia-ml name some tools dlopen.
rm -f /usr/share/vulkan/icd.d/nouveau_icd.*.json
ln -sf libnvidia-ml.so.1 /usr/lib64/libnvidia-ml.so

# The installer rewrote the dracut config to force-load the driver; rebuild
# the initramfs the way ublue's initramfs.sh does. dracut logs one FAILED line
# for /root (a symlink into /var on this base); it is benign, dracut exits 0.
export DRACUT_NO_XATTR=1
dracut --no-hostonly --kver "${image_kernel}" --reproducible -v --add ostree \
    -f "/usr/lib/modules/${image_kernel}/initramfs.img"
chmod 0600 "/usr/lib/modules/${image_kernel}/initramfs.img"
