#!/usr/bin/bash
# Host-side: bash tests/test-hypr-theme.sh (from the repo root)
# Exercises the theme engine against the fixture share in tests/fixtures/hypr-theme.
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

export PATH="$PWD/files/usr/bin:$PATH"
export HYPR_THEME_SHARE="$PWD/tests/fixtures/hypr-theme/share"
export HYPR_THEME_STATE="$(mktemp -d)"
export HYPR_THEME_NO_APPLY=1
# A throwaway HOME so a real ~/Pictures/Wallpapers never joins the rotation.
export HOME="$(mktemp -d)"
unset HYPRLAND_INSTANCE_SIGNATURE

check bash -c 'hypr-theme list | grep -qx "fixture"'
check hypr-theme set fixture
check grep -qx 'bg=#0a0a0a strip=39ff14 rgb=57,255,20 cur=breeze_cursors' "$HYPR_THEME_STATE/current/theme/sample.conf"
check test "$(cat "$HYPR_THEME_STATE/current/theme.name")" = fixture
check test "$(hypr-theme current)" = fixture
check test "$(readlink "$HYPR_THEME_STATE/current/background")" = "$HYPR_THEME_SHARE/themes/fixture/backgrounds/00-a.png"
check grep -q 'hand-written' "$HYPR_THEME_STATE/current/theme/hand.theme"      # theme file beats template
check bash -c '! test -e "$HYPR_THEME_STATE/current/next-theme"'               # atomic swap left nothing behind
check bash -c 'hypr-theme bg next; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 01-b.png'
check bash -c 'hypr-theme bg next; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 00-a.png'   # wraps
check bash -c 'hypr-theme bg next; hypr-theme set fixture --keep-background; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 01-b.png'
check bash -c 'hypr-theme set fixture; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 00-a.png'   # plain set resets to the first
check bash -c 'hypr-theme bg set "$HYPR_THEME_SHARE/themes/fixture/backgrounds/01-b.png"; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 01-b.png'
# overlay precedence: user copy of the theme wins over the shipped one
check bash -c 'mkdir -p "$HYPR_THEME_STATE/themes/fixture" && printf "background = \"#111111\"\naccent = \"#39ff14\"\ncursor_theme = \"x\"\n" > "$HYPR_THEME_STATE/themes/fixture/colors.toml" && hypr-theme set fixture && grep -q "bg=#111111" "$HYPR_THEME_STATE/current/theme/sample.conf"'
# user template wins over the shipped template
check bash -c 'mkdir -p "$HYPR_THEME_STATE/themed" && echo "mine={{ accent }}" > "$HYPR_THEME_STATE/themed/sample.conf.tpl" && hypr-theme refresh && grep -qx "mine=#39ff14" "$HYPR_THEME_STATE/current/theme/sample.conf"'
# refresh is idempotent: checksum unchanged, no rewrite
check bash -c 'before=$(stat -c %Y "$HYPR_THEME_STATE/current/theme/sample.conf"); sleep 1; hypr-theme refresh; test "$(stat -c %Y "$HYPR_THEME_STATE/current/theme/sample.conf")" = "$before"'
# unresolved placeholder is an error naming template and key, exit 2, current theme untouched
check bash -c 'echo "x={{ nope }}" > "$HYPR_THEME_STATE/themed/bad.tpl"; hypr-theme refresh 2>&1 | grep -q "bad.tpl: unresolved placeholder {{ nope }}"; rc=${PIPESTATUS[0]}; rm "$HYPR_THEME_STATE/themed/bad.tpl"; test "$rc" = 2'
check grep -qx 'mine=#39ff14' "$HYPR_THEME_STATE/current/theme/sample.conf"
check bash -c '! test -e "$HYPR_THEME_STATE/current/next-theme"'
# bad names (Review Focus 1)
for bad in "../x" "a/b" "Fixture" "has space" ""; do
    check bash -c "! hypr-theme set '$bad' >/dev/null 2>&1"
done
check test "$(hypr-theme current)" = fixture
check bash -c 'hypr-theme set nonexistent 2>&1 | grep -q "unknown theme: nonexistent"'
check bash -c '! hypr-theme set nonexistent >/dev/null 2>&1'
check test "$(hypr-theme render "$HYPR_THEME_SHARE/themed/sample.conf.tpl" "$HYPR_THEME_SHARE/themes/fixture/colors.toml")" = 'bg=#0a0a0a strip=39ff14 rgb=57,255,20 cur=breeze_cursors'
# user themes with a name of their own appear in list and can be set
check bash -c 'mkdir -p "$HYPR_THEME_STATE/themes/mine/backgrounds"; cp "$HYPR_THEME_SHARE/themes/fixture/colors.toml" "$HYPR_THEME_STATE/themes/mine/"; hypr-theme list | grep -qx mine; hypr-theme set mine; test "$(hypr-theme current)" = mine; hypr-theme set fixture'
# no session (Review Focus 3): unset the signature, drop NO_APPLY, stub the apply commands to a logging PATH
check bash -c 'unset HYPR_THEME_NO_APPLY HYPRLAND_INSTANCE_SIGNATURE; bin=$(mktemp -d); for c in hyprctl systemctl gsettings flatpak kvantummanager pkill swaybg; do printf "#!/bin/sh\necho called-%s >> %s\n" "$c" "$bin/log" > "$bin/$c"; chmod +x "$bin/$c"; done; PATH="$bin:$PATH" hypr-theme set fixture && ! test -e "$bin/log"'
# with a session the apply commands run
check bash -c 'unset HYPR_THEME_NO_APPLY; export HYPRLAND_INSTANCE_SIGNATURE=test; bin=$(mktemp -d); for c in hyprctl systemctl gsettings flatpak kvantummanager pkill swaybg; do printf "#!/bin/sh\necho called-%s >> %s\n" "$c" "$bin/log" > "$bin/$c"; chmod +x "$bin/$c"; done; PATH="$bin:$PATH" hypr-theme set fixture && grep -q called-hyprctl "$bin/log" && grep -q called-systemctl "$bin/log" && grep -q called-gsettings "$bin/log" && grep -q called-flatpak "$bin/log"'
# hook dir runs on apply (signature set, stub PATH, no --no-apply) and gets the theme name
check bash -c 'unset HYPR_THEME_NO_APPLY; export HYPRLAND_INSTANCE_SIGNATURE=test; bin=$(mktemp -d); for c in hyprctl systemctl gsettings flatpak kvantummanager pkill swaybg; do printf "#!/bin/sh\n" > "$bin/$c"; chmod +x "$bin/$c"; done; mkdir -p "$HYPR_THEME_STATE/hooks/theme-set.d"; printf "#!/bin/sh\necho \$1 > %s/hook.out\n" "$HYPR_THEME_STATE" > "$HYPR_THEME_STATE/hooks/theme-set.d/10-test"; chmod +x "$HYPR_THEME_STATE/hooks/theme-set.d/10-test"; PATH="$bin:$PATH" hypr-theme set fixture && test "$(cat "$HYPR_THEME_STATE/hook.out")" = fixture'
# --no-apply wins over a live session
check bash -c 'unset HYPR_THEME_NO_APPLY; export HYPRLAND_INSTANCE_SIGNATURE=test; bin=$(mktemp -d); for c in hyprctl systemctl gsettings flatpak kvantummanager pkill swaybg; do printf "#!/bin/sh\necho called >> %s\n" "$bin/log" > "$bin/$c"; chmod +x "$bin/$c"; done; PATH="$bin:$PATH" hypr-theme set fixture --no-apply && ! test -e "$bin/log"'
# usage errors
check bash -c '! hypr-theme >/dev/null 2>&1'
check bash -c '! hypr-theme bogus >/dev/null 2>&1'

exit "$fail"
