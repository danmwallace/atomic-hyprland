#!/usr/bin/bash
set -euo pipefail

dnf -y remove ansible-core python3-libdnf5
dnf -y copr disable atim/starship
dnf -y copr disable atim/lazygit
dnf -y copr disable lionheartp/Hyprland
dnf clean all

rm -rf /tmp/build /tmp/* /var/cache/* /var/log/* /var/roothome/.ansible /var/roothome/.cache
# Build-time clutter in /run (cloud-init, dnf, sddm, tuned); keep podman's own mounts.
find /run -mindepth 1 -maxdepth 1 ! -name .containerenv ! -name secrets ! -name systemd -exec rm -rf {} +
# /var must be empty-ish for bootc lint; list anything it still complains about here.

bootc container lint
