#!/usr/bin/bash
# Runs INSIDE the built image. Exercises /usr/libexec/atomic-hyprland/sync-dotfiles
# against a throwaway HOME and a throwaway copy of /usr/share/atomic-hyprland.
set -euo pipefail

sync=/usr/libexec/atomic-hyprland/sync-dotfiles
share="$(mktemp -d)"
export HOME="$(mktemp -d)"
export ATOMIC_HYPRLAND_SHARE="${share}"
cp -a /usr/share/atomic-hyprland/. "${share}/"

fail=0
expect() { if eval "$2"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }

# 1. first run populates managed files and writes the stamp
"${sync}"
expect "hyprland.conf synced" 'test -f "$HOME/.config/hypr/hyprland.conf"'
expect "waybar config synced" 'test -f "$HOME/.config/waybar/config"'
expect "stamp recorded" 'cmp -s "$share/stamp" "$HOME/.config/atomic-hyprland/stamp"'
expect "local.lua not in managed list" '! grep -qx ".config/hypr/local.lua" "$share/managed-files.txt"'

# 2. same stamp: no-op, user edits survive
echo "# user edit" >> "$HOME/.config/hypr/hyprland.conf"
printf 'hl.monitor({ output = "Virtual-1" })\n' > "$HOME/.config/hypr/local.lua"
out="$("${sync}")"
expect "second run reports up to date" '[[ "$out" == *"up to date"* ]]'
expect "user edit kept when stamp unchanged" 'grep -q "# user edit" "$HOME/.config/hypr/hyprland.conf"'

# 3. new stamp: managed files refreshed, local.conf untouched
echo "newer-build" > "${share}/stamp"
"${sync}"
expect "managed file refreshed after stamp change" '! grep -q "# user edit" "$HOME/.config/hypr/hyprland.conf"'
expect "local.lua survives resync" 'grep -q "Virtual-1" "$HOME/.config/hypr/local.lua"'
expect "new stamp recorded" 'grep -qx newer-build "$HOME/.config/atomic-hyprland/stamp"'

# 4. script mode preserved for executables
expect "sleep.sh stays executable" 'test -x "$HOME/.config/hypr/scripts/sleep.sh"'

# 5. a home that predates the image (no local.conf, e.g. after bootc switch)
#    gets local.conf exactly once; it is never rewritten afterwards
export HOME="$(mktemp -d)"
"${sync}"
expect "local.lua created for a pre-existing home" 'test -f "$HOME/.config/hypr/local.lua"'
printf 'hl.env("SENTINEL", "1")\n' > "$HOME/.config/hypr/local.lua"
echo "newest-build" > "${share}/stamp"
"${sync}"
expect "existing local.lua untouched on resync" 'grep -q SENTINEL "$HOME/.config/hypr/local.lua"'

# 5b. a home still holding the old .conf files: untouched, local.lua still created
export HOME="$(mktemp -d)"
mkdir -p "$HOME/.config/hypr"
echo "# old" > "$HOME/.config/hypr/hyprland.conf"
echo "# old" > "$HOME/.config/hypr/local.conf"
"${sync}"
expect "old hyprland.conf left in place" 'grep -q "^# old" "$HOME/.config/hypr/hyprland.conf"'
expect "old local.conf left in place" 'grep -q "^# old" "$HOME/.config/hypr/local.conf"'
expect "local.lua created beside the old files" 'test -f "$HOME/.config/hypr/local.lua"'
expect "hyprland.lua synced" 'test -f "$HOME/.config/hypr/hyprland.lua"'

# 6. unit is enabled for every user
expect "user unit enabled globally" 'test -L /etc/systemd/user/default.target.wants/atomic-hyprland-dotfiles.service'

exit "$fail"
