#!/usr/bin/bash
# Host-side: bash tests/test-skel-includes.sh (from the repo root)
# Every image-managed config carries its theme include and its local include, in the
# right order; the ownership lists know every local and retired path; templates render.
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

skel=files/etc/skel/.config
share=files/usr/share/atomic-hyprland
export PATH="$PWD/files/usr/bin:$PATH"
export HOME="$(mktemp -d)"

# wofi: launcher and power menu share one stylesheet
check grep -qx '@import "../atomic-hyprland/current/theme/wofi.css";' $skel/wofi/style.css
check bash -c "tail -1 $skel/wofi/style.css | grep -qx '@import \"local.css\";'"
check test -f $skel/wofi/local.css
check grep -qx 'term=ghostty' $skel/wofi/config
check grep -qx 'width=600' $skel/wofi/config
check grep -qx 'lines=8' $skel/wofi/config
check grep -q 'border-radius: 3px' $skel/wofi/style.css
check grep -q 'JetBrainsMono Nerd Font' $skel/wofi/style.css
# hyprlock
check grep -qx 'source = ~/.config/atomic-hyprland/current/theme/hyprlock.conf' $skel/hypr/hyprlock.conf
check grep -qx 'source = ~/.config/hypr/hyprlock.local.conf' $skel/hypr/hyprlock.conf
check grep -qx '    path = ~/.config/atomic-hyprland/current/background' $skel/hypr/hyprlock.conf
check grep -qx '    blur_passes = 0' $skel/hypr/hyprlock.conf
check grep -qx '    rounding = 3' $skel/hypr/hyprlock.conf
check grep -q 'outer_color = $accent' $skel/hypr/hyprlock.conf
check grep -q 'fail_color = $critical' $skel/hypr/hyprlock.conf
check grep -q 'font_family = JetBrainsMono Nerd Font' $skel/hypr/hyprlock.conf
check test -f $skel/hypr/hyprlock.local.conf
# ghostty
check grep -qx 'config-file = ?~/.config/atomic-hyprland/current/theme/ghostty.conf' $skel/ghostty/config
check bash -c "tail -1 $skel/ghostty/config | grep -qx 'config-file = ?~/.config/ghostty/local'"
check grep -qx 'font-family = JetBrainsMono Nerd Font' $skel/ghostty/config
check grep -qx 'font-size = 11' $skel/ghostty/config
check grep -qx 'window-padding-x = 8' $skel/ghostty/config
check test -f $skel/ghostty/local
# alacritty
check grep -q 'import = \["~/.config/atomic-hyprland/current/theme/alacritty.toml", "~/.config/alacritty/local.toml"\]' $skel/alacritty/alacritty.toml
check grep -q 'JetBrainsMono Nerd Font' $skel/alacritty/alacritty.toml
check test -f $skel/alacritty/local.toml
# btop
check test "$(readlink $skel/btop/themes/current.theme)" = ../../atomic-hyprland/current/theme/btop.theme
check grep -qx 'color_theme = "current"' $skel/btop/btop.conf
check grep -qx 'theme_background = False' $skel/btop/btop.conf
# ownership lists
check bash -c 'for f in .config/wofi/local.css .config/hypr/hyprlock.local.conf .config/ghostty/local .config/alacritty/local.toml .config/hypr/hypridle.local.conf .config/waybar/local.jsonc .config/waybar/local.css .config/mako/local .config/hypr/local.lua; do grep -qx "$f" '"$share"'/skel.local || { echo "missing $f"; exit 1; }; done'
check bash -c 'for f in .config/wofi/style-power.css .config/wofi/style-run.css .config/hypr/scripts/sleep.sh .config/hypr/xdg-portal-hyprland .config/nwg-drawer/ .config/nwg-dock-hyprland/ .config/waybar/config .config/waybar/mediaplayer.py .config/hypr/conf/; do grep -qxF "$f" '"$share"'/skel.retired || { echo "missing $f"; exit 1; }; done'
# the power menu
check test -x files/usr/bin/hypr-power
check bash -c 'bin=$(mktemp -d); printf "#!/bin/sh\necho \"󰌾 lock\"\n" > $bin/wofi; printf "#!/bin/sh\necho hyprlock-called > '"$HOME"'/out\n" > $bin/hyprlock; chmod +x $bin/*; PATH="$bin:$PATH" files/usr/bin/hypr-power; grep -q hyprlock-called '"$HOME"'/out'
check bash -c 'bin=$(mktemp -d); printf "#!/bin/sh\necho \"󰍃 logout\"\n" > $bin/wofi; printf "#!/bin/sh\necho \"uwsm \$*\" > '"$HOME"'/out\n" > $bin/uwsm; chmod +x $bin/*; PATH="$bin:$PATH" files/usr/bin/hypr-power; grep -qx "uwsm stop" '"$HOME"'/out'
check bash -c 'bin=$(mktemp -d); printf "#!/bin/sh\necho \"󰐥 shutdown\"\n" > $bin/wofi; printf "#!/bin/sh\necho \"systemctl \$*\" > '"$HOME"'/out\n" > $bin/systemctl; chmod +x $bin/*; PATH="$bin:$PATH" files/usr/bin/hypr-power; grep -qx "systemctl poweroff" '"$HOME"'/out'
check bash -c 'bin=$(mktemp -d); printf "#!/bin/sh\nexit 1\n" > $bin/wofi; chmod +x $bin/*; PATH="$bin:$PATH" files/usr/bin/hypr-power'   # cancelled menu is not an error
# every template renders for every theme and carries the right values
s=$(mktemp -d)
check env HYPR_THEME_SHARE=$share HYPR_THEME_STATE=$s HYPR_THEME_NO_APPLY=1 hypr-theme set monochrome-green
check grep -qx 'palette = 2=#39ff14' $s/current/theme/ghostty.conf
check grep -qx 'background = #0a0a0a' $s/current/theme/ghostty.conf
check grep -qx '$accent = rgb(39ff14)' $s/current/theme/hyprlock.conf
check grep -qx '$critical = rgb(e05050)' $s/current/theme/hyprlock.conf
check grep -q '^\[colors.primary\]' $s/current/theme/alacritty.toml
check grep -q 'green = "#39ff14"' $s/current/theme/alacritty.toml
check grep -q '@define-color accent #39ff14;' $s/current/theme/wofi.css
check grep -qF 'theme[main_bg]="#0a0a0a"' $s/current/theme/btop.theme
check grep -qF 'theme[hi_fg]="#39ff14"' $s/current/theme/btop.theme
check bash -c 'ls '"$s"'/current/theme/ | grep -qx chromium.theme || true'
for t in monochrome-blue tokyo-night nord dracula; do
    check env HYPR_THEME_SHARE=$share HYPR_THEME_STATE=$(mktemp -d) HYPR_THEME_NO_APPLY=1 hypr-theme set "$t"
done
check grep -qx btop build/packages.txt

# GTK, Qt, fonts
check grep -qx 'gtk-theme-name=Adwaita-dark' $skel/gtk-3.0/settings.ini
check grep -qx 'gtk-icon-theme-name=Papirus-Dark' $skel/gtk-3.0/settings.ini
check grep -qx 'gtk-cursor-theme-name=breeze_cursors' $skel/gtk-3.0/settings.ini
check grep -qx 'gtk-application-prefer-dark-theme=1' $skel/gtk-3.0/settings.ini
check test "$(readlink $skel/gtk-3.0/gtk.css)" = ../atomic-hyprland/current/theme/gtk.css
check test "$(readlink $skel/gtk-4.0/gtk.css)" = ../atomic-hyprland/current/theme/gtk.css
check grep -q '@define-color accent_bg_color #39ff14;' $s/current/theme/gtk.css
check grep -q '@define-color accent_fg_color #0a0a0a;' $s/current/theme/gtk.css
check grep -qx 'theme=KvGnomeDark' $skel/Kvantum/kvantum.kvconfig
check grep -q 'hl.env("QT_STYLE_OVERRIDE", "kvantum")' $share/hypr/env.lua
check bash -c '! grep -q qt6ct '"$share"'/hypr/env.lua'
check grep -q 'XCURSOR_THEME", palette.cursor_theme' $share/hypr/env.lua
check grep -q 'JetBrainsMono Nerd Font' files/etc/fonts/local.conf
check grep -q 'Inter' files/etc/fonts/local.conf
check bash -c 'xmllint --noout files/etc/fonts/local.conf 2>/dev/null || python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(\"files/etc/fonts/local.conf\")"'
check bash -c 'for p in papirus-icon-theme breeze-cursor-theme kvantum kvantum-qt5 gsettings-desktop-schemas dconf rsms-inter-fonts google-noto-emoji-color-fonts flatpak; do grep -qx "$p" build/packages.txt || { echo "missing $p"; exit 1; }; done'
check jq -e '.customManagers[] | select(.matchStrings[0] | test("NERD_FONT_VERSION")) | .depNameTemplate == "ryanoasis/nerd-fonts" and .datasourceTemplate == "github-releases"' renovate.json

exit "$fail"
