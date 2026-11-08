#!/usr/bin/bash
set -euo pipefail

# The ublue base ships Firefox as an RPM; on this image it is a Flatpak
# (see the control repo's desktop_flatpaks), like Bluefin does.
dnf -y remove firefox firefox-langpacks
dnf -y remove librsvg2-tools
dnf -y copr disable atim/starship
dnf -y copr disable atim/lazygit
dnf -y copr disable lionheartp/Hyprland
dnf -y copr disable scottames/ghostty
# Tailscale's repo is for the build; updates come with the image.
dnf5 config-manager setopt tailscale-stable.enabled=0
dnf clean all

rm -rf /tmp/build /tmp/* /var/cache/* /var/log/* /var/roothome/.cache
# Build-time clutter in /run (cloud-init, dnf, sddm, tuned); keep podman's own mounts.
find /run -mindepth 1 -maxdepth 1 ! -name .containerenv ! -name secrets ! -name systemd -exec rm -rf {} +
# /var must be empty-ish for bootc lint; list anything it still complains about here.

bootc container lint
