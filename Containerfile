# atomic-hyprland: Fedora 44 bootc image with Hyprland, built on Universal Blue base-main.
ARG BASE_IMAGE=ghcr.io/ublue-os/base-main:44
FROM ${BASE_IMAGE}

ARG THEME=nord
ARG NVIDIA=0
ARG IMAGE_VERSION=dev

COPY build/ /tmp/build/
COPY files/ /

RUN /tmp/build/10-packages.sh
RUN /tmp/build/20-hyprland-role.sh "${THEME}"
RUN if [ "${NVIDIA}" = "1" ]; then echo "NVIDIA layer arrives in Phase 4; build with NVIDIA=0" >&2; exit 1; fi
RUN /tmp/build/30-policy.sh && /tmp/build/40-finalize.sh "${IMAGE_VERSION}"
RUN /tmp/build/90-cleanup.sh

LABEL org.opencontainers.image.title="atomic-hyprland" \
      org.opencontainers.image.source="https://github.com/danmwallace/atomic-hyprland" \
      org.opencontainers.image.version="${IMAGE_VERSION}"
