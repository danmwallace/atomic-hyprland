#!/usr/bin/bash
# Host-side: bash tests/test-waybar.sh (from the repo root)
# The quiet bar: strict JSON, glyph-only defaults, theme include lines, session units,
# and the indicator scripts with and without the hardware they report on.
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
cfg=files/usr/share/atomic-hyprland/waybar/config.jsonc
thin=$skel/waybar/config.jsonc
units=files/usr/lib/systemd/user
libexec=files/usr/libexec/atomic-hyprland

check jq -e . "$cfg"
check bash -c 'jq -e ".\"modules-left\" == [\"hyprland/workspaces\",\"hyprland/window\"] and .\"modules-center\" == [\"clock\"]" '"$cfg"
check bash -c 'jq -e ".\"modules-right\" == [\"group/tray-drawer\",\"bluetooth\",\"network\",\"pulseaudio\",\"cpu\",\"memory\",\"custom/gpu\",\"custom/claude\",\"battery\",\"idle_inhibitor\",\"custom/notifications\",\"custom/power\"]" '"$cfg"
check bash -c 'jq -e ".layer == \"top\" and .position == \"top\" and .height == 30 and .\"margin-top\" == 8 and .\"margin-left\" == 8 and .\"margin-right\" == 8 and .reload_style_on_change == true" '"$cfg"
# waybar: the FIRST definition wins across includes, so the skel file is thin and
# names the local file before the shipped config
check jq -e . "$thin"
check bash -c 'jq -e ".include == [\"~/.config/waybar/local.jsonc\", \"/usr/share/atomic-hyprland/waybar/config.jsonc\"] and (keys | length) == 1" '"$thin"
# waybar formats dates with fmt's chrono, which has no glibc %-d flag (it rejects the whole format)
check bash -c '! jq -r ".clock.format" '"$cfg"' | grep -q "%-"'
check bash -c 'jq -r ".clock.format" '"$cfg"' | grep -q "%H:%M"'
check bash -c '! jq -e ".include" '"$cfg"' >/dev/null'
# glyph-only default formats: no numbers in the right-hand modules' default format
check bash -c 'for m in cpu memory battery network pulseaudio bluetooth; do jq -er ".\"$m\".format" '"$cfg"' | grep -qE "\{(capacity|usage|percentage|volume|essid|ipaddr|signalStrength)" && exit 1; done; exit 0'
# ...but the numbers are in the tooltips
check bash -c 'jq -er ".cpu.\"tooltip-format\"" '"$cfg"' | grep -q "{usage}"'
check bash -c 'jq -er ".memory.\"tooltip-format\"" '"$cfg"' | grep -q "{used"'
check bash -c 'jq -er ".battery.\"tooltip-format\"" '"$cfg"' | grep -q "{capacity}"'
check bash -c 'jq -er ".\"custom/gpu\".exec" '"$cfg"' | grep -q "/usr/libexec/atomic-hyprland/waybar/gpu"'
check bash -c 'jq -e ".\"custom/gpu\".\"return-type\" == \"json\"" '"$cfg"
check bash -c 'jq -er ".\"custom/notifications\".exec" '"$cfg"' | grep -q "/usr/libexec/atomic-hyprland/waybar/notifications"'
check bash -c 'jq -e ".battery.states.critical == 15 and .battery.states.warning == 30" '"$cfg"
check bash -c 'jq -er ".\"custom/power\".\"on-click\"" '"$cfg"' | grep -qx hypr-power'
check bash -c 'jq -e ".\"hyprland/workspaces\".\"persistent-workspaces\".\"*\" == 5" '"$cfg"
check bash -c 'jq -e ".\"group/tray-drawer\".modules[0] == \"custom/tray-toggle\" and (.\"group/tray-drawer\".modules | index(\"tray\")) != null" '"$cfg"
check bash -c '! jq -e ".\"custom/media\" or .\"custom/updates\" or .backlight or .\"hyprland/submap\"" '"$cfg"' >/dev/null'
check bash -c 'head -1 '"$skel"'/waybar/style.css | grep -qx "@import \"../atomic-hyprland/current/theme/waybar.css\";"'
check bash -c 'tail -1 '"$skel"'/waybar/style.css | grep -qx "@import \"local.css\";"'
check grep -q '#battery.charging' $skel/waybar/style.css
check grep -q '#battery.critical' $skel/waybar/style.css
check grep -q '#custom-gpu.critical' $skel/waybar/style.css
check grep -q '#pulseaudio.muted' $skel/waybar/style.css
check grep -q '#network.disconnected' $skel/waybar/style.css
check grep -q '#idle_inhibitor.activated' $skel/waybar/style.css
check grep -q 'JetBrainsMono Nerd Font' $skel/waybar/style.css
check grep -q 'border-radius: 3px' $skel/waybar/style.css
check jq -e . $skel/waybar/local.jsonc
check test -f $skel/waybar/local.css
# theme template defines the colours the stylesheet uses
for c in background surface foreground foreground_dim accent accent_dim warning critical; do
    check grep -q "^@define-color $c " files/usr/share/atomic-hyprland/themed/waybar.css.tpl
done
check grep -q '@define-color background {{ background_alt }};' files/usr/share/atomic-hyprland/themed/waybar.css.tpl

# indicator scripts emit valid JSON with and without hardware (Review Focus 5)
bin=$(mktemp -d); fakeproc=$(mktemp -d); mkdir -p "$fakeproc/driver/nvidia"; echo x > "$fakeproc/driver/nvidia/version"
printf '#!/bin/sh\necho 71\n' > "$bin/nvidia-smi"; chmod +x "$bin/nvidia-smi"
check bash -c 'PATH="'"$bin"':$PATH" GPU_PROC_ROOT="'"$fakeproc"'" '"$libexec"'/waybar/gpu | jq -e ".percentage == 71 and .class == \"normal\" and .text == \"󰢮\" and (.tooltip | test(\"gpu 71\"))"'
printf '#!/bin/sh\necho 84\n' > "$bin/nvidia-smi"
check bash -c 'PATH="'"$bin"':$PATH" GPU_PROC_ROOT="'"$fakeproc"'" '"$libexec"'/waybar/gpu | jq -e ".class == \"critical\" and .percentage == 84"'
# no card: the CPU path, still JSON (hwmon root overridable for the test)
fakesys=$(mktemp -d); mkdir -p "$fakesys/hwmon0"; echo coretemp > "$fakesys/hwmon0/name"; echo 45000 > "$fakesys/hwmon0/temp1_input"
check bash -c 'GPU_PROC_ROOT="$(mktemp -d)" HWMON_ROOT="'"$fakesys"'" '"$libexec"'/waybar/gpu | jq -e ".percentage == 45 and .class == \"normal\" and (.tooltip | test(\"cpu 45\"))"'
check bash -c 'GPU_PROC_ROOT="$(mktemp -d)" HWMON_ROOT="$(mktemp -d)" '"$libexec"'/waybar/gpu | jq -e ".text and .tooltip"'   # nothing readable at all: still JSON
# a runtime-suspended dGPU must not be woken by nvidia-smi every 5 s: fall back to the CPU reading
pci=$(mktemp -d); mkdir -p "$pci/0000:01:00.0/power"; echo 0x030000 > "$pci/0000:01:00.0/class"; echo 0x10de > "$pci/0000:01:00.0/vendor"; echo suspended > "$pci/0000:01:00.0/power/runtime_status"
printf '#!/bin/sh\necho woke > %s/woke; echo 71\n' "$bin" > "$bin/nvidia-smi"; rm -f "$bin/woke"
check bash -c 'PATH="'"$bin"':$PATH" GPU_PROC_ROOT="'"$fakeproc"'" PCI_ROOT="'"$pci"'" HWMON_ROOT="'"$fakesys"'" '"$libexec"'/waybar/gpu | jq -e ".percentage == 45 and (.tooltip | test(\"cpu\"))" && ! test -e '"$bin"'/woke'
echo active > "$pci/0000:01:00.0/power/runtime_status"
check bash -c 'PATH="'"$bin"':$PATH" GPU_PROC_ROOT="'"$fakeproc"'" PCI_ROOT="'"$pci"'" HWMON_ROOT="'"$fakesys"'" '"$libexec"'/waybar/gpu | jq -e ".percentage == 71" && test -e '"$bin"'/woke'
# notifications: makoctl mode output drives the class
printf '#!/bin/sh\necho default\n' > "$bin/makoctl"; chmod +x "$bin/makoctl"
check bash -c 'PATH="'"$bin"':$PATH" '"$libexec"'/waybar/notifications | jq -e ".class == \"normal\" and .text == \"󰂚\""'
printf '#!/bin/sh\nprintf "default\\ndo-not-disturb\\n"\n' > "$bin/makoctl"
check bash -c 'PATH="'"$bin"':$PATH" '"$libexec"'/waybar/notifications | jq -e ".class == \"dnd\" and .text == \"󰂛\""'
check bash -c 'PATH="$(mktemp -d)" '"$libexec"'/waybar/notifications | jq -e ".text"'   # no makoctl: still JSON

# mako
check bash -c 'head -1 files/usr/share/atomic-hyprland/themed/mako.ini.tpl | grep -qx "include=/usr/share/atomic-hyprland/mako/core.ini"'
# mako accepts include= only in the global section: the local include must come before the first [section]
check bash -c 'awk "/^\\[/{exit} /^include=~\/.config\/mako\/local/{found=1} END{exit !found}" files/usr/share/atomic-hyprland/themed/mako.ini.tpl'
check awk '/^\[/{s=1} s && /^include=/{bad=1} END{exit bad}' files/usr/share/atomic-hyprland/themed/mako.ini.tpl
check grep -q '^border-radius=3' files/usr/share/atomic-hyprland/mako/core.ini
check grep -q '^margin=46,12,0,0' files/usr/share/atomic-hyprland/mako/core.ini
# do-not-disturb is a mode mako must be told about, or the bell toggle does nothing
check grep -q '^\[mode=do-not-disturb\]' files/usr/share/atomic-hyprland/mako/core.ini
check bash -c 'awk "/^\\[mode=do-not-disturb\\]/{s=1;next} /^\\[/{s=0} s && /^invisible=1/{f=1} END{exit !f}" files/usr/share/atomic-hyprland/mako/core.ini'
check grep -q '^default-timeout=6000' files/usr/share/atomic-hyprland/mako/core.ini
check grep -q 'border-color={{ accent }}' files/usr/share/atomic-hyprland/themed/mako.ini.tpl
check grep -q 'border-color={{ critical }}' files/usr/share/atomic-hyprland/themed/mako.ini.tpl
check test "$(readlink $skel/mako/config)" = ../atomic-hyprland/current/theme/mako.ini
check test -f $skel/mako/local

# session units: waybar, mako and hypridle ship their own graphical-session units in
# their RPMs (checked in the image smoke test); the repo adds swaybg and the battery timer.
check bash -c '! test -e '"$units"'/waybar.service && ! test -e '"$units"'/mako.service && ! test -e '"$units"'/hypridle.service'
check grep -q '^WantedBy=graphical-session.target' $units/swaybg.service
check grep -q '^PartOf=graphical-session.target' $units/swaybg.service
check grep -q '^After=graphical-session.target' $units/swaybg.service
check grep -q '^WantedBy=graphical-session.target' $units/atomic-hyprland-battery.timer
check grep -q 'current/background' $units/swaybg.service
check grep -q '^Restart=on-failure' $units/swaybg.service
check grep -q 'ConditionPathExistsGlob=/sys/class/power_supply/BAT' $units/atomic-hyprland-battery.service
check grep -q '^OnUnitActiveSec=2min' $units/atomic-hyprland-battery.timer
check test -x $libexec/battery-warn
# battery-warn: notifies once below 15 %, resets when charging (fake sysfs)
fakebat=$(mktemp -d); mkdir -p "$fakebat/BAT1"; echo 12 > "$fakebat/BAT1/capacity"; echo Discharging > "$fakebat/BAT1/status"
printf '#!/bin/sh\necho "$@" >> %s/notify.log\n' "$bin" > "$bin/notify-send"; chmod +x "$bin/notify-send"; rm -f "$bin/notify.log"
check bash -c 'PATH="'"$bin"':$PATH" POWER_SUPPLY_ROOT="'"$fakebat"'" BATTERY_WARN_STATE="'"$fakebat"'/state" '"$libexec"'/battery-warn; grep -q -- "-u critical" '"$bin"'/notify.log'
check bash -c 'PATH="'"$bin"':$PATH" POWER_SUPPLY_ROOT="'"$fakebat"'" BATTERY_WARN_STATE="'"$fakebat"'/state" '"$libexec"'/battery-warn; test "$(grep -c critical '"$bin"'/notify.log)" = 1'   # not twice
check bash -c 'echo Charging > '"$fakebat"'/BAT1/status; PATH="'"$bin"':$PATH" POWER_SUPPLY_ROOT="'"$fakebat"'" BATTERY_WARN_STATE="'"$fakebat"'/state" '"$libexec"'/battery-warn; ! test -e '"$fakebat"'/state'
check bash -c '! grep -qE "waybar|swaybg|hypridle|mako" files/usr/share/atomic-hyprland/hypr/autostart.lua'
# hypridle: lock at 5 min, dpms at 10, battery-only suspend at 20, locks before sleep, local include
check grep -q 'timeout = 300' $skel/hypr/hypridle.conf
check grep -q 'timeout = 600' $skel/hypr/hypridle.conf
check grep -q 'timeout = 1200' $skel/hypr/hypridle.conf
check grep -q 'before_sleep_cmd = loginctl lock-session' $skel/hypr/hypridle.conf
check grep -q 'source = ~/.config/hypr/hypridle.local.conf' $skel/hypr/hypridle.conf
check test -f $skel/hypr/hypridle.local.conf
# ownership lists
check bash -c 'for f in .config/waybar/local.jsonc .config/waybar/local.css .config/mako/local .config/hypr/hypridle.local.conf; do grep -qx "$f" files/usr/share/atomic-hyprland/skel.local || exit 1; done'
check bash -c 'for f in .config/waybar/config .config/waybar/mediaplayer.py; do grep -qx "$f" files/usr/share/atomic-hyprland/skel.retired || exit 1; done'
check grep -q 'waybar.service mako.service swaybg.service hypridle.service atomic-hyprland-battery.timer' build/40-finalize.sh
check bash -c 'grep -qx mako build/packages.txt && grep -qx libnotify build/packages.txt'

exit "$fail"
