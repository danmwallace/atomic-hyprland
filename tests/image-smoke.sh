#!/usr/bin/bash
# Runs INSIDE the built image: podman run --rm -v ./tests:/tests:ro,Z IMAGE bash /tests/image-smoke.sh
set -uo pipefail

fail=0
check() {
    if "$@" >/dev/null 2>&1; then
        echo "ok    $*"
    else
        echo "FAIL  $*"
        fail=1
    fi
}

check rpm -q hyprland hyprlock hypridle hyprpaper xdg-desktop-portal-hyprland
# Transitional: the .conf-to-Lua port targets 0.56; a COPR bump must fail the build, not ship.
check bash -c 'rpm -q --qf "%{VERSION}\n" hyprland | grep -q "^0\.56\."'
check rpm -q sddm sddm-x11 waybar wofi alacritty swaybg cliphist
check rpm -q elvish starship lazygit fzf ripgrep fd-find bat git gh jq yq uv distrobox
check rpm -q cloud-init qemu-guest-agent
check bash -c '! rpm -q fish'
check bash -c '! rpm -q ansible-core'
check test -f /etc/skel/.config/hypr/hyprland.conf
check test -f /etc/skel/.config/hypr/local.conf
check grep -q '^source = ~/.config/hypr/local.conf' /etc/skel/.config/hypr/hyprland.conf
check test -f /usr/share/wayland-sessions/hyprland.desktop
# Wallpaper: the config must point at a file that exists on a fresh install.
check test -f /usr/share/backgrounds/images/earth_from_space.jpg
check grep -q '^exec-once = swaybg -m fill -i /usr/share/backgrounds/images/earth_from_space.jpg' /etc/skel/.config/hypr/hyprland.conf
check grep -q 'path = /usr/share/backgrounds/images/earth_from_space.jpg' /etc/skel/.config/hypr/hyprlock.conf
# The rendered config must parse cleanly on the Hyprland the image ships
# (upstream removes options between releases). Runs as root in this test
# container, hence the explicit root override flag.
check bash -c 'export HOME=/tmp/hv XDG_RUNTIME_DIR=/tmp/hv/run; mkdir -p "$HOME/.config" "$XDG_RUNTIME_DIR" && cp -r /etc/skel/.config/hypr "$HOME/.config/" && Hyprland --verify-config --i-am-really-stupid --config "$HOME/.config/hypr/hyprland.conf"'
check test -L /etc/systemd/system/display-manager.service
check test "$(readlink -f /etc/systemd/system/default.target)" = /usr/lib/systemd/system/graphical.target
check grep -q '^/usr/bin/elvish$' /etc/shells
check jq -e '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"][0].type == "insecureAcceptAnything"' /etc/containers/policy.json
# Only the COPRs this build enables (new-style file names); the ublue base ships
# its own _copr_ublue-os-akmods.repo enabled and that is left as-is.
check bash -c '! grep -ls "^enabled=1" /etc/yum.repos.d/_copr:copr.fedorainfracloud.org:*.repo'
check test -s /usr/share/atomic-hyprland/stamp
check test -f /usr/share/atomic-hyprland/skel/.config/hypr/hyprland.conf
check bash -c '! test -e /var/roothome/.ansible'
check bash -c 'test -z "$(ls -A /var/cache 2>/dev/null)"'

exit "$fail"
