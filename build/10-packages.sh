#!/usr/bin/bash
set -euo pipefail
claude_code_version="${1:?claude code version}"
tuios_version="${2:?tuios version}"
tuios_sha256="${3:?tuios sha256}"

# COPRs are enabled only for the build; 90-cleanup.sh disables them again.
dnf -y copr enable atim/starship
dnf -y copr enable atim/lazygit
dnf -y copr enable lionheartp/Hyprland
dnf -y copr enable scottames/ghostty

mapfile -t packages < <(grep -vE '^\s*(#|$)' /tmp/build/packages.txt)
dnf -y install --setopt=install_weak_deps=False "${packages[@]}"

# Claude Code for every user (Dan and the hermes agent). On this image
# /usr/local and /root point into /var, which does not exist at build time, so
# install under /usr explicitly and keep npm's cache out of the image.
npm_config_cache=/tmp/build/npm-cache npm install -g --prefix /usr "@anthropic-ai/claude-code@${claude_code_version}"

# tuios is not packaged for Fedora; upstream ships one static Go binary per
# release. Version and sha256 are both pinned in the Containerfile, so a
# replaced or tampered release asset fails the build. Renovate proposes the
# version bump; the hash is updated by hand in the same PR.
tuios_tar="tuios_${tuios_version}_Linux_x86_64.tar.gz"
tuios_url="https://github.com/Gaurav-Gosain/tuios/releases/download/v${tuios_version}"
mkdir -p /tmp/build/tuios
curl -fsSL -o "/tmp/build/tuios/${tuios_tar}" "${tuios_url}/${tuios_tar}"
( cd /tmp/build/tuios && echo "${tuios_sha256}  ${tuios_tar}" | sha256sum -c - )
tar -xzf "/tmp/build/tuios/${tuios_tar}" -C /tmp/build/tuios tuios LICENSE
install -m 0755 /tmp/build/tuios/tuios /usr/bin/tuios
install -D -m 0644 /tmp/build/tuios/LICENSE /usr/share/licenses/tuios/LICENSE
