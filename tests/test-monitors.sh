#!/usr/bin/bash
# Host-side: bash tests/test-monitors.sh (from the repo root)
# Display rules and scaling: the LG OLED TV, the catch-all, and how apps that
# are not native Wayland are scaled.
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

m=files/usr/share/atomic-hyprland/hypr/monitors.lua
lg="$(grep 'desc:LG Electronics LG TV SSCR2 0x01010101' "$m")"
export lg
# LG OLED TV: 4K at 120 Hz, scale 1.5 = a 2560x1440 desktop
check bash -c 'grep -q "mode = \"3840x2160@120\"" <<< "$lg"'
check bash -c 'grep -q "scale = 1.5" <<< "$lg"'
# VRR in fullscreen only (2): always-on VRR flickers on OLED as the desktop's rate swings
check bash -c 'grep -q "vrr = 2" <<< "$lg"'
check bash -c 'grep -q "bitdepth = 10" <<< "$lg"'
# an unknown display picks its own scale instead of a tiny scale 1
check grep -q 'output = "",.*scale = "auto"' "$m"
# XWayland apps render at full resolution instead of being upscaled blurry
check grep -qE 'force_zero_scaling *= *true' "$m"
# Electron apps (Slack, Orca, ...) run as native Wayland clients, so they scale sharply
check grep -qx 'export ELECTRON_OZONE_PLATFORM_HINT=auto' files/etc/xdg/uwsm/env-hyprland
check grep -q 'hl.env("ELECTRON_OZONE_PLATFORM_HINT", "auto")' files/usr/share/atomic-hyprland/hypr/env.lua

exit "$fail"
