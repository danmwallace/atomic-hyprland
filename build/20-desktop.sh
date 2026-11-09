#!/usr/bin/bash
# Desktop assets that need a build step: the Nerd Font and the per-theme
# wallpapers (SVG -> PNG). The Hyprland config, themes and templates arrive by
# COPY files/ before this.
set -euo pipefail
nerd_font_version="${1:?nerd font version}"
nerd_font_sha256="${2:?nerd font sha256}"
nerd_firacode_sha256="${3:?FiraCode nerd font sha256}"

# Build-time only; removed in 90-cleanup.sh.
dnf -y install --setopt=install_weak_deps=False librsvg2-tools

# Nerd Fonts: not packaged for Fedora; upstream's release tarballs, pinned by
# version and sha256 in the Containerfile so a replaced asset fails the build.
# Renovate proposes the version; the hashes are updated by hand. FiraCode is
# the default monospace (terminals, bar, menus, lock screen); JetBrainsMono
# stays installed to pick per user.
mkdir -p /tmp/build/nerd
install_nerd_font() { # install_nerd_font TARBALL SHA256 /usr/share/fonts/DIR
    local tar="$1" sha="$2" dir="$3"
    curl -fsSL -o "/tmp/build/nerd/${tar}" "https://github.com/ryanoasis/nerd-fonts/releases/download/v${nerd_font_version}/${tar}"
    ( cd /tmp/build/nerd && echo "${sha}  ${tar}" | sha256sum -c - )
    install -d -m 0755 "${dir}"
    tar -xJf "/tmp/build/nerd/${tar}" -C "${dir}" --wildcards '*.ttf'
    chmod 0644 "${dir}"/*.ttf
}
nerd_tar=JetBrainsMono.tar.xz
install_nerd_font "${nerd_tar}" "${nerd_font_sha256}" /usr/share/fonts/jetbrains-mono-nerd
install_nerd_font FiraCode.tar.xz "${nerd_firacode_sha256}" /usr/share/fonts/firacode-nerd
fc-cache -f

/tmp/build/render-wallpapers.sh

# SDDM runs as root before any theme is chosen, so its colours are rendered
# once here from the default theme.
sddm_theme=/usr/share/sddm/themes/atomic-hyprland
hypr-theme render "${sddm_theme}/theme.conf.tpl" /usr/share/atomic-hyprland/themes/monochrome-green/colors.toml > "${sddm_theme}/theme.conf"
rm -f "${sddm_theme}/theme.conf.tpl"
