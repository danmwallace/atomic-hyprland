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
check test -f /etc/skel/.config/hypr/hyprland.lua
check test -f /etc/skel/.config/hypr/conf/binds.lua
check test -f /etc/skel/.config/hypr/local.lua
check bash -c '! test -e /etc/skel/.config/hypr/hyprland.conf'
check bash -c '! test -e /etc/skel/.config/hypr/local.conf'
check grep -q 'pcall(require, "local")' /etc/skel/.config/hypr/hyprland.lua
check test -f /usr/share/wayland-sessions/hyprland.desktop
# Wallpaper: the config must point at a file that exists on a fresh install.
check test -f /usr/share/backgrounds/images/earth_from_space.jpg
check grep -q '^exec-once = swaybg -m fill -i /usr/share/backgrounds/images/earth_from_space.jpg' /etc/skel/.config/hypr/hyprland.conf
check grep -q 'path = /usr/share/backgrounds/images/earth_from_space.jpg' /etc/skel/.config/hypr/hyprlock.conf
# Hyprland's own parser on the skel tree, without --config so its file selection picks hyprland.lua.
verify_hypr() {
    export HOME=/tmp/hv XDG_RUNTIME_DIR=/tmp/hv/run
    rm -rf /tmp/hv; mkdir -p "$HOME/.config" "$XDG_RUNTIME_DIR"
    cp -r /etc/skel/.config/hypr "$HOME/.config/"
    [ -n "${1:-}" ] && echo "$1" >> "$HOME/.config/hypr/conf/binds.lua"
    Hyprland --verify-config --i-am-really-stupid 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
}
# expect_out <label> <present|absent> <regex>  (matches against $out)
expect_out() {
    local hit=1; grep -Eq "$3" <<< "$out" && hit=0
    if { [ "$2" = present ] && [ $hit = 0 ]; } || { [ "$2" = absent ] && [ $hit = 1 ]; }; then
        echo "ok    $1"
    else
        echo "FAIL  $1"; fail=1
    fi
}
out="$(verify_hypr)"
expect_out "hyprland verify-config reports config ok" present 'config ok'
expect_out "hyprland verify-config has no Lua or config errors" absent 'attempt to|stack traceback|Config error'
expect_out "hyprland picked the Lua config" present 'Using lua config'
# Error isolation: a broken binds.lua must be reported by name while the entry file still loads.
out="$(verify_hypr 'hl.bind("SUPER + Z", hl.dsp.nonexistent())')"
expect_out "broken binds.lua is reported by name" present 'binds.lua'
expect_out "broken binds.lua does not fail hyprland.lua" absent 'hyprland.lua:'
check rpm -q hyprland-guiutils
check bash -c "fc-match -f '%{family}' RobotoMonoNerdFontPropo | grep -q 'Nerd Font Propo'"
check bash -c '! grep -q "custom/updates" /etc/skel/.config/waybar/config'
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
