#!/usr/bin/bash
# Host-side: bash tests/test-openrgb-hook.sh (from the repo root)
# The shipped theme hook that sets RGB lighting to the theme's led colour.
# openrgb, systemd-run and systemctl are stubs that log their arguments.
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

hook="$PWD/files/usr/share/atomic-hyprland/hooks/theme-set.d/50-openrgb"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# fresh <led-line>: a new HOME/state with a rendered theme, and an empty stub dir.
fresh() {
    rm -rf "$work"/*
    mkdir -p "$work/home" "$work/stubs" "$work/state/current/theme"
    printf 'accent = "#3d9bff"\n%s\n' "$1" > "$work/state/current/theme/colors.toml"
    for c in systemd-run systemctl; do
        printf '#!/bin/sh\necho "%s $*" >> "%s/log"\n' "$c" "$work" > "$work/stubs/$c"
        chmod +x "$work/stubs/$c"
    done
}
stub_openrgb() { # stub_openrgb PATH: an openrgb that records its arguments
    mkdir -p "$(dirname "$1")"
    printf '#!/bin/sh\necho "openrgb $*" >> "%s/log"\n' "$work" > "$1"
    chmod +x "$1"
}
run() { HOME="$work/home" HYPR_THEME_STATE="$work/state" PATH="$work/stubs:/usr/bin:/bin" "$hook" demo; }
export -f run fresh stub_openrgb
export hook work

check test -x "$hook"

# No OpenRGB anywhere: succeed and do nothing.
fresh 'led = "#39ff14"'
check run
check bash -c '! test -e "$work/log"'

# openrgb on PATH: a transient user unit sets every device to the led colour.
fresh 'led = "#39ff14"'; stub_openrgb "$work/stubs/openrgb"; run
check grep -q 'systemd-run .*--user' "$work/log"
check grep -q 'systemd-run .*--unit=atomic-hyprland-leds' "$work/log"
check grep -qE "systemd-run .* -- $work/stubs/openrgb --noautoconnect --mode static --color 39FF14\$" "$work/log"
# a newer switch replaces one still in flight
check grep -q 'systemctl --user stop atomic-hyprland-leds.service' "$work/log"
check bash -c '[ "$(grep -n "systemctl" "$work/log" | cut -d: -f1)" -lt "$(grep -n "systemd-run" "$work/log" | cut -d: -f1)" ]'

# A theme without led (a user's own theme) falls back to the accent.
fresh ''; stub_openrgb "$work/stubs/openrgb"; run
check grep -q -- '--color 3D9BFF$' "$work/log"

# The OpenRGB AppImage in ~/AppImages is found when openrgb is not on PATH.
fresh 'led = "#ff2a3d"'; stub_openrgb "$work/home/AppImages/OpenRGB_0.9_x86_64.AppImage"; run
check grep -qE -- "-- $work/home/AppImages/OpenRGB_0.9_x86_64.AppImage --noautoconnect --mode static --color FF2A3D\$" "$work/log"
# ...but not one that is not executable
fresh 'led = "#ff2a3d"'; stub_openrgb "$work/home/AppImages/openrgb.appimage"; chmod -x "$work/home/AppImages/openrgb.appimage"
check run
check bash -c '! test -e "$work/log"'

# Without systemd-run (no user manager) it runs OpenRGB itself, in the background.
fresh 'led = "#39ff14"'; stub_openrgb "$work/stubs/openrgb"; rm "$work/stubs/systemd-run"; run
check bash -c 'for i in $(seq 50); do grep -q "^openrgb --noautoconnect --mode static --color 39FF14$" "$work/log" 2>/dev/null && exit 0; sleep 0.1; done; exit 1'

# A malformed colour is never passed on.
fresh 'led = "red"'; printf 'accent = "nope"\nled = "red"\n' > "$work/state/current/theme/colors.toml"; stub_openrgb "$work/stubs/openrgb"
check run
check bash -c '! grep -q -- --color "$work/log" 2>/dev/null'

exit "$fail"
