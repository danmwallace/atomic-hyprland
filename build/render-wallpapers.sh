#!/usr/bin/bash
# Build time: render themed/wallpaper.svg.tpl for every shipped theme into
# themes/<name>/backgrounds/00-plain.png (3840x2160). Needs rsvg-convert
# (librsvg2-tools), installed for the build and removed by 90-cleanup.sh.
set -euo pipefail

share="${HYPR_THEME_SHARE:-/usr/share/atomic-hyprland}"
export HYPR_THEME_SHARE="${share}" HYPR_THEME_NO_APPLY=1
for dir in "${share}"/themes/*/; do
    name="$(basename "${dir}")"
    state="$(mktemp -d)"
    HYPR_THEME_STATE="${state}" HOME="${state}" hypr-theme set "${name}" >/dev/null
    mkdir -p "${dir}/backgrounds"
    rsvg-convert -w 3840 -h 2160 "${state}/current/theme/wallpaper.svg" -o "${dir}/backgrounds/00-plain.png"
    rm -rf "${state}"
    echo "rendered ${dir}backgrounds/00-plain.png"
done
