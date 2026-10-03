#!/usr/bin/bash
set -euo pipefail

# COPRs are enabled only for the build; 90-cleanup.sh disables them again.
dnf -y copr enable atim/starship
dnf -y copr enable atim/lazygit
dnf -y copr enable lionheartp/Hyprland

mapfile -t packages < <(grep -vE '^\s*(#|$)' /tmp/build/packages.txt)
dnf -y install --setopt=install_weak_deps=False "${packages[@]}"

# Build-time only; removed in 90-cleanup.sh.
dnf -y install --setopt=install_weak_deps=False ansible-core python3-libdnf5
