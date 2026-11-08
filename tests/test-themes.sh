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

themes="monochrome-green monochrome-blue tokyo-night nord dracula"
required="background background_glow background_alt surface foreground foreground_dim accent accent_dim warning critical selection_background selection_foreground cursor_theme $(seq -f 'color%g' 0 15 | tr '\n' ' ')"
share=files/usr/share/atomic-hyprland
export HOME="$(mktemp -d)"

for t in $themes; do
    f="$share/themes/$t/colors.toml"
    check test -f "$f"
    check test -s "$share/themes/$t/icons.theme"
    for k in $required; do check grep -qE "^$k = \"" "$f"; done
    # every colour is 6-digit lower-case hex; cursor_theme is a plain word
    check bash -c "! grep -E '^(color[0-9]+|background.*|surface|foreground.*|accent.*|warning|critical|selection_.*) = ' '$f' | grep -vqE '= \"#[0-9a-f]{6}\"$'"
    # no extra keys beyond the set, so no template can depend on a key another theme lacks
    check bash -c "diff <(grep -oE '^[a-z0-9_]+' '$f' | sort) <(tr ' ' '\n' <<< '$required' | grep . | sort)"
done
check test "$(grep -E '^accent = ' $share/themes/monochrome-green/colors.toml)" = 'accent = "#39ff14"'
check test "$(grep -E '^accent = ' $share/themes/monochrome-blue/colors.toml)" = 'accent = "#3d9bff"'
check test "$(grep -E '^background = ' $share/themes/monochrome-green/colors.toml)" = 'background = "#0a0a0a"'
check test "$(grep -E '^cursor_theme = ' $share/themes/monochrome-green/colors.toml)" = 'cursor_theme = "breeze_cursors"'
# every shipped template renders against every theme with no unresolved placeholder (Review Focus 2)
for t in $themes; do
    check env HYPR_THEME_SHARE="$share" HYPR_THEME_STATE="$(mktemp -d)" HYPR_THEME_NO_APPLY=1 files/usr/bin/hypr-theme set "$t"
done
check test -f $share/themed/wallpaper.svg.tpl
check grep -q '{{ background_glow }}' $share/themed/wallpaper.svg.tpl
check grep -q 'width="3840" height="2160"' $share/themed/wallpaper.svg.tpl
check test -x build/render-wallpapers.sh
check grep -q 'rsvg-convert' build/render-wallpapers.sh
check grep -q '00-plain.png' build/render-wallpapers.sh

exit "$fail"
