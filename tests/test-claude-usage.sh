#!/usr/bin/bash
# Host-side: bash tests/test-claude-usage.sh (from the repo root)
# The Claude usage widget: claude-statusline caches Claude Code's documented
# status line rate_limits; waybar/claude renders the cache. Clock and zone fixed.
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

libexec="$PWD/files/usr/libexec/atomic-hyprland"
sl="$libexec/claude-statusline"
wb="$libexec/waybar/claude"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export XDG_CACHE_HOME="$work/cache" TZ=UTC
# 2026-11-08 20:00:00 UTC
export CLAUDE_USAGE_NOW=1794168000
cache="$XDG_CACHE_HOME/atomic-hyprland/claude-usage.json"
# pkill is stubbed so the test never signals a real waybar
mkdir -p "$work/bin"; printf '#!/bin/sh\necho "pkill $*" >> %s/pkill.log\n' "$work" > "$work/bin/pkill"; chmod +x "$work/bin/pkill"
export PATH="$work/bin:$PATH"

payload() { # payload FIVE_PCT FIVE_RESET WEEK_PCT WEEK_RESET -> status line JSON
    printf '{"model":{"id":"claude-opus-5-5","display_name":"Opus 5.5"},"session_id":"s","rate_limits":{"five_hour":{"used_percentage":%s,"resets_at":%s},"seven_day":{"used_percentage":%s,"resets_at":%s}}}' "$@"
}
export -f payload
export sl wb cache work

check test -x "$sl"
check test -x "$wb"

# Nothing cached yet: the module hides itself (empty text) and still prints JSON.
check bash -c '"$wb" | jq -e ".text == \"\""'

# The status line: prints a one-line summary for Claude Code and caches the numbers.
out="$(payload 23.5 1794186000 41.2 1794571200 | "$sl")"
check test "$out" = "Opus 5.5 · 5h 24% · wk 41%"
check jq -e '.five_hour.used_percentage == 23.5 and .seven_day.resets_at == 1794571200 and .updated_at == 1794168000 and .model == "Opus 5.5"' "$cache"
check grep -q -- '-RTMIN+9 -x waybar' "$work/pkill.log"   # bar refreshes at once

# The bar: both windows, rounded, with the glyph; normal class; reset times in the tooltip.
check bash -c '"$wb" | jq -e ".text == \"󰚩 24% · 41%\""'
check bash -c '"$wb" | jq -e ".class == [\"normal\"] and .percentage == 41"'
check bash -c '"$wb" | jq -r .tooltip | grep -q "5-hour  24%  resets 01:00"'      # within a day: time only
check bash -c '"$wb" | jq -r .tooltip | grep -q "weekly  41%  resets Fri 12:00"'  # further out: weekday too
check bash -c '"$wb" | jq -r .tooltip | grep -q "updated just now"'

# Thresholds use the higher window: 75 warning, 90 critical.
payload 80 1794186000 41 1794571200 | "$sl" >/dev/null
check bash -c '"$wb" | jq -e ".class == [\"warning\"]"'
payload 10 1794186000 92 1794571200 | "$sl" >/dev/null
check bash -c '"$wb" | jq -e ".class == [\"critical\"] and .percentage == 92"'

# A payload without rate_limits (before the session's first API reply) keeps the cache.
before="$(cat "$cache")"
printf '{"model":{"display_name":"Opus 5.5"}}' | "$sl" > "$work/out"
check test "$(cat "$work/out")" = "Opus 5.5"
check test "$(cat "$cache")" = "$before"
# Garbage in: still prints something, never breaks the cache.
check bash -c 'echo "not json" | "$sl"'
check test "$(cat "$cache")" = "$before"

# Old numbers are dimmed (stale after 15 min) and say how old they are.
payload 23 1794186000 41 1794571200 | "$sl" >/dev/null
check bash -c 'CLAUDE_USAGE_NOW=$((1794168000 + 20*60)) "$wb" | jq -e ".class == [\"normal\",\"stale\"]"'
check bash -c 'CLAUDE_USAGE_NOW=$((1794168000 + 20*60)) "$wb" | jq -r .tooltip | grep -q "updated 20 min ago"'
# A window whose reset has passed shows a dash: the old number no longer applies.
check bash -c 'CLAUDE_USAGE_NOW=$((1794186000 + 60)) "$wb" | jq -e ".text == \"󰚩 – · 41%\""'
check bash -c 'CLAUDE_USAGE_NOW=$((1794186000 + 60)) "$wb" | jq -r .tooltip | grep -q "5-hour  reset since"'

# A missing window (Claude Code may omit either) is a dash too.
printf '{"model":{"display_name":"Opus 5.5"},"rate_limits":{"seven_day":{"used_percentage":5,"resets_at":1794571200}}}' | "$sl" >/dev/null
check bash -c '"$wb" | jq -e ".text == \"󰚩 – · 5%\""'

# A corrupt cache hides the module rather than breaking the bar.
echo '{' > "$cache"
check bash -c '"$wb" | jq -e ".text == \"\""'

# --- claude-statusline-setup: offers the status line once per user, at login ---
setup="$libexec/claude-statusline-setup"
export setup
check test -x "$setup"
want='{"type":"command","command":"/usr/libexec/atomic-hyprland/claude-statusline"}'
export want
fresh_home() { rm -rf "$work/h"; mkdir -p "$work/h"; }
export -f fresh_home
runs() { HOME="$work/h" XDG_STATE_HOME="$work/h/.local/state" "$setup"; }
export -f runs
# No settings.json yet: created with just the status line, private directory.
check bash -c 'fresh_home; runs && jq -e --argjson w "$want" ".statusLine == \$w and (keys == [\"statusLine\"])" "$work/h/.claude/settings.json"'
check bash -c 'fresh_home; runs && test "$(stat -c %a "$work/h/.claude")" = 700'
# An existing settings.json keeps every other key.
check bash -c 'fresh_home; mkdir -p "$work/h/.claude"; echo "{\"model\":\"opus\",\"permissions\":{\"allow\":[\"Bash(ls)\"]}}" > "$work/h/.claude/settings.json"; runs && jq -e --argjson w "$want" ".statusLine == \$w and .model == \"opus\" and .permissions.allow == [\"Bash(ls)\"]" "$work/h/.claude/settings.json"'
# A status line the user already has is never replaced.
check bash -c 'fresh_home; mkdir -p "$work/h/.claude"; echo "{\"statusLine\":{\"type\":\"command\",\"command\":\"mine\"}}" > "$work/h/.claude/settings.json"; runs && jq -e ".statusLine.command == \"mine\"" "$work/h/.claude/settings.json"'
# Once offered, never again: removing it afterwards sticks.
check bash -c 'fresh_home; runs; echo "{}" > "$work/h/.claude/settings.json"; runs && jq -e ". == {}" "$work/h/.claude/settings.json"'
# A settings.json that is not valid JSON is left untouched (and offered again next login).
check bash -c 'fresh_home; mkdir -p "$work/h/.claude"; echo "{ broken" > "$work/h/.claude/settings.json"; runs; test "$(cat "$work/h/.claude/settings.json")" = "{ broken"'
check bash -c 'fresh_home; mkdir -p "$work/h/.claude"; echo "{ broken" > "$work/h/.claude/settings.json"; runs; echo "{}" > "$work/h/.claude/settings.json"; runs && jq -e --argjson w "$want" ".statusLine == \$w" "$work/h/.claude/settings.json"'

# --- wiring: the bar module, its style, and the login unit ---
cfg=files/usr/share/atomic-hyprland/waybar/config.jsonc
check bash -c 'jq -e ".\"custom/claude\".exec == \"/usr/libexec/atomic-hyprland/waybar/claude\" and .\"custom/claude\".\"return-type\" == \"json\" and .\"custom/claude\".signal == 9 and .\"custom/claude\".interval == 60" '"$cfg"
check bash -c 'jq -e ".\"modules-right\" | index(\"custom/claude\") == (index(\"custom/gpu\") + 1)" '"$cfg"
check grep -q '#custom-claude.warning' files/etc/skel/.config/waybar/style.css
check grep -q '#custom-claude.critical' files/etc/skel/.config/waybar/style.css
check grep -q '#custom-claude.stale' files/etc/skel/.config/waybar/style.css
unit=files/usr/lib/systemd/user/atomic-hyprland-claude-statusline.service
check grep -qx 'ExecStart=/usr/libexec/atomic-hyprland/claude-statusline-setup' "$unit"
check grep -qx 'WantedBy=default.target' "$unit"
check grep -q 'systemctl --global enable atomic-hyprland-claude-statusline.service' build/40-finalize.sh

exit "$fail"
