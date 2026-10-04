#!/usr/bin/bash
set -euo pipefail
claude_code_version="${1:?claude code version}"

# COPRs are enabled only for the build; 90-cleanup.sh disables them again.
dnf -y copr enable atim/starship
dnf -y copr enable atim/lazygit
dnf -y copr enable lionheartp/Hyprland

mapfile -t packages < <(grep -vE '^\s*(#|$)' /tmp/build/packages.txt)
dnf -y install --setopt=install_weak_deps=False "${packages[@]}"

# Build-time only; removed in 90-cleanup.sh.
dnf -y install --setopt=install_weak_deps=False ansible-core python3-libdnf5

# Claude Code for every user (Dan and the hermes agent). On this image
# /usr/local and /root point into /var, which does not exist at build time, so
# install under /usr explicitly and keep npm's cache out of the image.
npm_config_cache=/tmp/build/npm-cache npm install -g --prefix /usr "@anthropic-ai/claude-code@${claude_code_version}"
