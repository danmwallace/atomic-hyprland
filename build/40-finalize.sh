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

# The elvish RPM does not register itself; chsh and cloud-init need it listed.
grep -qx /usr/bin/elvish /etc/shells || echo /usr/bin/elvish >> /etc/shells

# Pristine copy of the rendered skel plus a stamp, for the login-time sync
# (Task 4) and for `bootc` users created before an image update.
install -d /usr/share/atomic-hyprland
cp -a /etc/skel /usr/share/atomic-hyprland/skel
printf '%s\n' "${version}" > /usr/share/atomic-hyprland/stamp

# Files the login-time sync may overwrite. local.lua is deliberately excluded.
( cd /etc/skel && find .config -type f ! -path '.config/hypr/local.lua' | sort ) \
    > /usr/share/atomic-hyprland/managed-files.txt

systemctl --global enable atomic-hyprland-dotfiles.service
