# atomic-hyprland: Fedora 44 bootc image with Hyprland, built on Universal Blue base-main.
ARG BASE_IMAGE=ghcr.io/ublue-os/base-main:44
# No default: it must be the akmods build for the base's kernel. `just build`
# passes the pinned pair from build/images.env.
ARG AKMODS_IMAGE

# NVIDIA kmod, userspace driver and ublue's installer, for the bind mount below.
FROM ${AKMODS_IMAGE} AS akmods

# The image itself. This must stay the last FROM.
FROM ${BASE_IMAGE}

ARG IMAGE_VERSION=dev
ARG CLAUDE_CODE_VERSION=2.1.289
ARG TUIOS_VERSION=0.12.1
# sha256 of tuios_${TUIOS_VERSION}_Linux_x86_64.tar.gz. Bump it by hand with
# the version: take the line for that file from the release's checksums.txt.
ARG TUIOS_SHA256=4f68bac6e05d826b8c59b671b565c61b859dacedcb5d889160ba6d8624589b50
# JetBrainsMono Nerd Font release tarball; sha256 from the release's SHA-256.txt,
# verified against the downloaded asset before pinning. Bump both together.
ARG NERD_FONT_VERSION=3.5.1
ARG NERD_FONT_SHA256=04d5e8f903693f9dd13e16f867e994834e681eb3c72c0d337a770dcda09010cf

COPY build/ /tmp/build/

RUN /tmp/build/10-packages.sh "${CLAUDE_CODE_VERSION}" "${TUIOS_VERSION}" "${TUIOS_SHA256}"
# The bind mount keeps a gigabyte of driver RPMs out of the image layers.
RUN --mount=type=bind,from=akmods,src=/rpms,dst=/tmp/akmods-rpms /tmp/build/25-nvidia.sh

# Static files: the Hyprland config, themes, templates, units and hypr-theme.
# They land after the package layers so editing them does not invalidate the
# package cache, and before 20-desktop.sh, which renders the wallpapers with them.
COPY files/ /
COPY --chmod=0644 cosign.pub /etc/pki/containers/atomic-hyprland.pub
RUN /tmp/build/20-desktop.sh "${NERD_FONT_VERSION}" "${NERD_FONT_SHA256}"
RUN /tmp/build/30-policy.sh && /tmp/build/40-finalize.sh "${IMAGE_VERSION}"
RUN /tmp/build/90-cleanup.sh

LABEL org.opencontainers.image.title="atomic-hyprland" \
      org.opencontainers.image.source="https://github.com/danmwallace/atomic-hyprland" \
      org.opencontainers.image.version="${IMAGE_VERSION}"
