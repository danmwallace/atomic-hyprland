#!/usr/bin/bash
set -euo pipefail
version="${1:?image version}"

systemctl enable sddm.service
systemctl enable ai-images-pull.service
systemctl set-default graphical.target

# bootc stages updates (drop-in makes it stage-only); rpm-ostree's updater
# would race it for the same deployment slot, so only one is enabled.
systemctl enable bootc-fetch-apply-updates.timer
systemctl disable rpm-ostreed-automatic.timer

# Compile the dconf system defaults (/etc/dconf/db/local.d) into /etc/dconf/db/local.
dconf update

# The elvish RPM does not register itself; chsh and cloud-init need it listed.
grep -qx /usr/bin/elvish /etc/shells || echo /usr/bin/elvish >> /etc/shells

# Pristine copy of the rendered skel plus a stamp, for the login-time sync
# (Task 4) and for `bootc` users created before an image update.
install -d /usr/share/atomic-hyprland
cp -a /etc/skel /usr/share/atomic-hyprland/skel
printf '%s\n' "${version}" > /usr/share/atomic-hyprland/stamp

# Files the login-time sync may overwrite: everything in skel except the
# user's files listed in skel.local (local.lua and the per-app local includes).
( cd /etc/skel && find .config \( -type f -o -type l \) | sort ) \
    | grep -vxFf <(grep -vE '^\s*(#|$)' /usr/share/atomic-hyprland/skel.local) \
    > /usr/share/atomic-hyprland/managed-files.txt

systemctl --global enable atomic-hyprland-dotfiles.service
systemctl --global enable atomic-hyprland-theme@.service
# Session services: uwsm starts graphical-session.target, which pulls these in.
systemctl --global enable waybar.service mako.service swaybg.service hypridle.service atomic-hyprland-battery.timer
