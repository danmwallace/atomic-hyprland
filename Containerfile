# atomic-hyprland: Fedora 44 bootc image with Hyprland, built on Universal Blue base-main.
ARG BASE_IMAGE=ghcr.io/ublue-os/base-main:44
FROM ${BASE_IMAGE}

ARG THEME=nord
ARG NVIDIA=0
ARG IMAGE_VERSION=dev
ARG CLAUDE_CODE_VERSION=2.1.289

COPY build/ /tmp/build/

RUN /tmp/build/10-packages.sh "${CLAUDE_CODE_VERSION}"
RUN /tmp/build/20-hyprland-role.sh "${THEME}"
RUN if [ "${NVIDIA}" = "1" ]; then echo "NVIDIA layer arrives in Phase 4; build with NVIDIA=0" >&2; exit 1; fi

# Static files land after the expensive layers so editing them does not
# invalidate the package and role cache.
COPY files/ /
COPY --chmod=0644 cosign.pub /etc/pki/containers/atomic-hyprland.pub
RUN /tmp/build/30-policy.sh && /tmp/build/40-finalize.sh "${IMAGE_VERSION}"
RUN /tmp/build/90-cleanup.sh

LABEL org.opencontainers.image.title="atomic-hyprland" \
      org.opencontainers.image.source="https://github.com/danmwallace/atomic-hyprland" \
      org.opencontainers.image.version="${IMAGE_VERSION}"
