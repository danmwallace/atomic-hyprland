#!/usr/bin/bash
# Host-side: bash tests/test-themes.sh (from the repo root)
# Every shipped theme has the same key set, valid colours, and renders every template.
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

share=files/usr/share/atomic-hyprland
expected="catppuccin-mocha dracula everforest gruvbox-dark kanagawa monochrome-amber monochrome-blue monochrome-cyan monochrome-green monochrome-magenta monochrome-orange monochrome-red monochrome-violet neon-night nord rose-pine tokyo-night"
# Every theme directory is checked, and the shipped set is exactly the expected one.
themes="$(find "$share/themes" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | tr '\n' ' ')"
check test "$themes" = "$expected "
required="background background_glow background_alt surface foreground foreground_dim accent accent_dim led warning critical selection_background selection_foreground cursor_theme $(seq -f 'color%g' 0 15 | tr '\n' ' ')"
export HOME="$(mktemp -d)"

for t in $themes; do
    f="$share/themes/$t/colors.toml"
    check test -f "$f"
    check test -s "$share/themes/$t/icons.theme"
    for k in $required; do check grep -qE "^$k = \"" "$f"; done
    # every colour is 6-digit lower-case hex; cursor_theme is a plain word
    check bash -c "! grep -E '^(color[0-9]+|background.*|surface|foreground.*|accent.*|led|warning|critical|selection_.*) = ' '$f' | grep -vqE '= \"#[0-9a-f]{6}\"$'"
    # no extra keys beyond the set, so no template can depend on a key another theme lacks
    check bash -c "diff <(grep -oE '^[a-z0-9_]+' '$f' | sort) <(tr ' ' '\n' <<< '$required' | grep . | sort)"
done
check test "$(grep -E '^accent = ' $share/themes/monochrome-green/colors.toml)" = 'accent = "#39ff14"'
check test "$(grep -E '^accent = ' $share/themes/monochrome-blue/colors.toml)" = 'accent = "#3d9bff"'
check test "$(grep -E '^background = ' $share/themes/monochrome-green/colors.toml)" = 'background = "#0a0a0a"'
check test "$(grep -E '^cursor_theme = ' $share/themes/monochrome-green/colors.toml)" = 'cursor_theme = "breeze_cursors"'
# led is what keyboard/case lighting shows (hooks/theme-set.d/50-openrgb). LEDs wash out
# pale colours to white, so every led needs a dominant channel: max - min >= 0x80.
for t in $themes; do
    led="$(sed -nE 's/^led = "#([0-9a-f]{6})"$/\1/p' "$share/themes/$t/colors.toml")"
    check bash -c "r=\$((16#${led:0:2})) g=\$((16#${led:2:2})) b=\$((16#${led:4:2})); mx=\$(printf '%s\\n' \$r \$g \$b | sort -n | tail -1); mn=\$(printf '%s\\n' \$r \$g \$b | sort -n | head -1); (( mx - mn >= 128 ))  # $t led #$led"
done
# saturated accents drive the LEDs as they are
for t in monochrome-green monochrome-amber monochrome-red gruvbox-dark neon-night; do
    check test "$(sed -n 's/^led = //p' "$share/themes/$t/colors.toml")" = "$(sed -n 's/^accent = //p' "$share/themes/$t/colors.toml")"
done
# every shipped template renders against every theme with no unresolved placeholder (Review Focus 2)
for t in $themes; do
    check env HYPR_THEME_SHARE="$share" HYPR_THEME_STATE="$(mktemp -d)" HYPR_THEME_NO_APPLY=1 files/usr/bin/hypr-theme set "$t"
done
# OLED mode renders every theme on true black (bar background included)
for t in $themes; do
    check bash -c "st=\$(mktemp -d); : > \$st/oled; HYPR_THEME_SHARE='$share' HYPR_THEME_STATE=\$st HYPR_THEME_NO_APPLY=1 files/usr/bin/hypr-theme set '$t' && grep -q '@define-color background #000000;' \$st/current/theme/waybar.css"
done
check test -f $share/backgrounds/oled-black.png
check test -f $share/themed/wallpaper.svg.tpl
check grep -q '{{ background_glow }}' $share/themed/wallpaper.svg.tpl
check grep -q 'width="3840" height="2160"' $share/themed/wallpaper.svg.tpl
# the default glow is visible (Dan, 2026-11-08: "a bit too dark, I can barely see the gradient"),
# and it fades softly over most of the screen to the theme background at the edges
check test "$(grep -E '^background_glow = ' $share/themes/monochrome-green/colors.toml)" = 'background_glow = "#2a2a2a"'
check grep -q 'offset="85%" stop-color="{{ background_glow }}" stop-opacity="0"' $share/themed/wallpaper.svg.tpl
check grep -q '<rect width="3840" height="2160" fill="{{ background }}"/>' $share/themed/wallpaper.svg.tpl
check grep -q 'background_glow = "2a2a2a"' files/etc/skel/.config/hypr/hyprland.lua   # fallback palette matches
check test -x build/render-wallpapers.sh
check grep -q 'rsvg-convert' build/render-wallpapers.sh
check grep -q '00-plain.png' build/render-wallpapers.sh

exit "$fail"
