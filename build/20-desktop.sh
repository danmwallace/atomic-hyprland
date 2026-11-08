#!/usr/bin/bash
# Desktop assets that need a build step: the Nerd Font and the per-theme
# wallpapers (SVG -> PNG). The Hyprland config, themes and templates arrive by
# COPY files/ before this.
set -euo pipefail
nerd_font_version="${1:?nerd font version}"
nerd_font_sha256="${2:?nerd font sha256}"

# Build-time only; removed in 90-cleanup.sh.
dnf -y install --setopt=install_weak_deps=False librsvg2-tools

# JetBrainsMono Nerd Font: not packaged for Fedora; upstream's release tarball,
# pinned by version and sha256 in the Containerfile so a replaced asset fails
# the build. Renovate proposes the version; the hash is updated by hand.
nerd_tar=JetBrainsMono.tar.xz
nerd_url="https://github.com/ryanoasis/nerd-fonts/releases/download/v${nerd_font_version}/${nerd_tar}"
mkdir -p /tmp/build/nerd
curl -fsSL -o "/tmp/build/nerd/${nerd_tar}" "${nerd_url}"
( cd /tmp/build/nerd && echo "${nerd_font_sha256}  ${nerd_tar}" | sha256sum -c - )
install -d -m 0755 /usr/share/fonts/jetbrains-mono-nerd
tar -xJf "/tmp/build/nerd/${nerd_tar}" -C /usr/share/fonts/jetbrains-mono-nerd --wildcards '*.ttf'
chmod 0644 /usr/share/fonts/jetbrains-mono-nerd/*.ttf
fc-cache -f

/tmp/build/render-wallpapers.sh
