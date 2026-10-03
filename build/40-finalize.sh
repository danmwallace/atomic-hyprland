#!/usr/bin/bash
set -euo pipefail
version="${1:?image version}"

systemctl enable sddm.service
systemctl set-default graphical.target

# The elvish RPM does not register itself; chsh and cloud-init need it listed.
grep -qx /usr/bin/elvish /etc/shells || echo /usr/bin/elvish >> /etc/shells

# Pristine copy of the rendered skel plus a stamp, for the login-time sync
# (Task 4) and for `bootc` users created before an image update.
install -d /usr/share/atomic-hyprland
cp -a /etc/skel /usr/share/atomic-hyprland/skel
printf '%s\n' "${version}" > /usr/share/atomic-hyprland/stamp

# Files the login-time sync may overwrite. local.conf is deliberately excluded.
( cd /etc/skel && find .config -type f ! -path '.config/hypr/local.conf' | sort ) \
    > /usr/share/atomic-hyprland/managed-files.txt

systemctl --global enable atomic-hyprland-dotfiles.service
