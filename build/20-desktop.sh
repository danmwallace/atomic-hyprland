#!/usr/bin/bash
# Desktop assets that need a build step: the per-theme wallpapers (SVG -> PNG).
# The Hyprland config, themes and templates arrive by COPY files/ before this.
set -euo pipefail

# Build-time only; removed in 90-cleanup.sh.
dnf -y install --setopt=install_weak_deps=False librsvg2-tools

/tmp/build/render-wallpapers.sh
