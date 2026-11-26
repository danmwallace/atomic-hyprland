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
# A pinned version is a commit SHA (7-40 hex) or a numeric tag (v1.2.3), never a branch.
pin_re='@([0-9a-f]{7,40}|v?[0-9]+(\.[0-9]+)*)/'
for good in "x@0d8c7aaea33c655bb9e4c93d352a28f3baa69a75/y" "x@v1.2.3/y" "x@1234567/y"; do check grep -qE "$pin_re" <<< "$good"; done
for bad in "x@dev/y" "x@develop/y" "x@beta/y" "x@feature-x/y" "x@main/y" "x@latest/y" "x/y"; do check bash -c "! grep -qE '$pin_re' <<< '$bad'"; done

for t in $themes; do
    f="$share/themes/$t/colors.toml"
    check test -f "$f"
    check test -s "$share/themes/$t/icons.theme"
    # apps.toml names the theme's counterpart in Helix and Vesktop (hooks 40-helix, 41-vesktop)
    a="$share/themes/$t/apps.toml"
    check test -f "$a"
    check bash -c "diff <(grep -oE '^[a-z_]+' '$a' | sort) <(printf 'helix\nvesktop\n')"
    check grep -qE '^helix = "[A-Za-z0-9_+-]+"$' "$a"
    check grep -qE "^vesktop = \"https://[^\"]+$pin_re[^\"]+\"\$" "$a"
    check bash -c "! grep -qE '@(main|master)/|/refs/heads/' '$a'"
    for k in $required; do check grep -qE "^$k = \"" "$f"; done
    # every colour is 6-digit lower-case hex; cursor_theme is a plain word
    check bash -c "! grep -E '^(color[0-9]+|background.*|surface|foreground.*|accent.*|led|warning|critical|selection_.*) = ' '$f' | grep -vqE '= \"#[0-9a-f]{6}\"$'"
    # no extra keys beyond the set, so no template can depend on a key another theme lacks
    check bash -c "diff <(grep -oE '^[a-z0-9_]+' '$f' | sort) <(tr ' ' '\n' <<< '$required' | grep . | sort)"
done
check test "$(grep -E '^helix = ' $share/themes/tokyo-night/apps.toml)" = 'helix = "tokyonight"'
check test "$(grep -E '^helix = ' $share/themes/catppuccin-mocha/apps.toml)" = 'helix = "catppuccin_mocha"'
check test "$(grep -E '^helix = ' $share/themes/monochrome-red/apps.toml)" = 'helix = "base16_terminal"'
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
# gtk.css sets libadwaita's named colours from the theme; adw-gtk3 reads the same
# names for GTK3, and Chromium in GTK mode follows GTK3 (app theming, Task 5)
gtk_names="window_bg_color window_fg_color view_bg_color view_fg_color headerbar_bg_color headerbar_fg_color card_bg_color popover_bg_color sidebar_bg_color accent_color accent_bg_color accent_fg_color"
for t in $themes; do
    css="$(files/usr/bin/hypr-theme render "$share/themed/gtk.css.tpl" "$share/themes/$t/colors.toml")"
    for n in $gtk_names; do
        check grep -qE "^@define-color $n #[0-9a-f]{6};$" <<< "$css"
    done
done
# readable everywhere: foreground on each GTK background keeps WCAG contrast >= 4.5
for t in $themes; do
    check python3 - "$share/themes/$t/colors.toml" <<'PY'
import sys, re
c = dict(re.findall(r'^([a-z0-9_]+) = "#([0-9a-f]{6})"$', open(sys.argv[1]).read(), re.M))
def lum(h):
    ch = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)
bad = [(bg, round(ratio(c["foreground"], c[bg]), 2)) for bg in ("background", "background_alt", "surface") if ratio(c["foreground"], c[bg]) < 4.5]
sys.exit(1 if bad else 0)
PY
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
