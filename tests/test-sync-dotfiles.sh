#!/usr/bin/bash
# Runs INSIDE the built image (just test). Exercises the login-time scripts
# against a throwaway HOME and a throwaway copy of /usr/share/atomic-hyprland.
#
# Host variant (before an image exists):
#   SYNC_HOST=1 PATH="$PWD/files/usr/bin:$PATH" bash tests/test-sync-dotfiles.sh
# uses the scripts from files/ and the fixture share; the unit-file checks are
# skipped there and proven at the next image build.
set -euo pipefail

if [[ -n "${SYNC_HOST:-}" ]]; then
    export PATH="$PWD/files/usr/bin:$PATH"
    sync="$PWD/files/usr/libexec/atomic-hyprland/sync-dotfiles"
    ensure="$PWD/files/usr/libexec/atomic-hyprland/ensure-theme"
    src_share="$PWD/tests/fixtures/sync/share"
else
    sync=/usr/libexec/atomic-hyprland/sync-dotfiles
    ensure=/usr/libexec/atomic-hyprland/ensure-theme
    src_share=/usr/share/atomic-hyprland
fi
share="$(mktemp -d)"
export HOME="$(mktemp -d)"
export ATOMIC_HYPRLAND_SHARE="${share}"
cp -a "${src_share}/." "${share}/"
# A managed executable to prove modes are preserved (the image's skel has none we rely on).
install -D -m 0755 /dev/stdin "${share}/skel/.config/test-exec.sh" <<< '#!/bin/sh'
echo '.config/test-exec.sh' >> "${share}/managed-files.txt"

fail=0
expect() { if eval "$2"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }
unit_expect() { if [[ -n "${SYNC_HOST:-}" ]]; then echo "skip  $1 (host run)"; else expect "$1" "$2"; fi; }

# 1. first run populates managed files and writes the stamp
"${sync}"
expect "hyprland.lua synced" 'test -f "$HOME/.config/hypr/hyprland.lua"'
expect "stamp recorded" 'cmp -s "$share/stamp" "$HOME/.config/atomic-hyprland/stamp"'
expect "local.lua not in managed list" '! grep -qx ".config/hypr/local.lua" "$share/managed-files.txt"'
expect "local.lua listed in skel.local" 'grep -qx ".config/hypr/local.lua" "$share/skel.local"'

# 2. same stamp: no-op, user edits survive
echo "# user edit" >> "$HOME/.config/hypr/hyprland.lua"
printf 'hl.monitor({ output = "Virtual-1" })\n' > "$HOME/.config/hypr/local.lua"
out="$("${sync}")"
expect "second run reports up to date" '[[ "$out" == *"up to date"* ]]'
expect "user edit kept when stamp unchanged" 'grep -q "# user edit" "$HOME/.config/hypr/hyprland.lua"'

# 3. new stamp: managed files refreshed, local.lua untouched
echo "newer-build" > "${share}/stamp"
"${sync}"
expect "managed file refreshed after stamp change" '! grep -q "# user edit" "$HOME/.config/hypr/hyprland.lua"'
expect "local.lua survives resync" 'grep -q "Virtual-1" "$HOME/.config/hypr/local.lua"'
expect "new stamp recorded" 'grep -qx newer-build "$HOME/.config/atomic-hyprland/stamp"'

# 4. mode preserved for executables
expect "managed executable stays executable" 'test -x "$HOME/.config/test-exec.sh"'

# 5. a home that predates the image (no local.lua, e.g. after bootc switch)
#    gets local.lua exactly once; it is never rewritten afterwards
export HOME="$(mktemp -d)"
"${sync}"
expect "local.lua created for a pre-existing home" 'test -f "$HOME/.config/hypr/local.lua"'
printf 'hl.env("SENTINEL", "1")\n' > "$HOME/.config/hypr/local.lua"
echo "newest-build" > "${share}/stamp"
"${sync}"
expect "existing local.lua untouched on resync" 'grep -q SENTINEL "$HOME/.config/hypr/local.lua"'

# 5b. a home still holding the pre-Lua .conf files: untouched, local.lua still created
export HOME="$(mktemp -d)"
mkdir -p "$HOME/.config/hypr"
echo "# old" > "$HOME/.config/hypr/hyprland.conf"
echo "# old" > "$HOME/.config/hypr/local.conf"
"${sync}"
expect "old hyprland.conf left in place" 'grep -q "^# old" "$HOME/.config/hypr/hyprland.conf"'
expect "old local.conf left in place" 'grep -q "^# old" "$HOME/.config/hypr/local.conf"'
expect "local.lua created beside the old files" 'test -f "$HOME/.config/hypr/local.lua"'

# 5c. symlinks in skel (mako config, gtk.css, btop theme) land as symlinks with the same relative target,
#     even though the target does not exist yet at sync time (the theme render comes later)
mkdir -p "${share}/skel/.config/mako"; ln -sfn ../atomic-hyprland/current/theme/mako.ini "${share}/skel/.config/mako/config"
echo '.config/mako/config' >> "${share}/managed-files.txt"
export HOME="$(mktemp -d)"; "${sync}"
expect "skel symlink synced as a symlink" 'test -L "$HOME/.config/mako/config"'
expect "symlink target kept relative" 'test "$(readlink "$HOME/.config/mako/config")" = ../atomic-hyprland/current/theme/mako.ini'
echo newer3 > "${share}/stamp"; "${sync}"
expect "symlink survives a resync" 'test -L "$HOME/.config/mako/config"'

# 6. units enabled for every user
unit_expect "dotfiles unit enabled globally" 'test -L /etc/systemd/user/default.target.wants/atomic-hyprland-dotfiles.service'

# 7. local files are created once and never rewritten
printf '.config/hypr/local.lua\n.config/waybar/local.jsonc\n.config/ghostty/local\n' > "${share}/skel.local"
mkdir -p "${share}/skel/.config/waybar" "${share}/skel/.config/ghostty"
echo '{}' > "${share}/skel/.config/waybar/local.jsonc"; : > "${share}/skel/.config/ghostty/local"
export HOME="$(mktemp -d)"; "${sync}"
expect "local.jsonc created" 'test "$(cat "$HOME/.config/waybar/local.jsonc")" = "{}"'
expect "empty ghostty local created" 'test -f "$HOME/.config/ghostty/local"'
echo '{"custom/x":{}}' > "$HOME/.config/waybar/local.jsonc"; echo newer2 > "${share}/stamp"; "${sync}"
expect "local.jsonc never rewritten" 'grep -q custom/x "$HOME/.config/waybar/local.jsonc"'
expect "local files not in managed list" '! grep -q "local.jsonc" "$share/managed-files.txt"'

# 8. retired paths are removed; user files beside them survive (Review Focus 4)
printf '# written by earlier images\n.config/waybar/config\n.config/hypr/conf/\n.config/nwg-drawer/\n' > "${share}/skel.retired"
export HOME="$(mktemp -d)"; mkdir -p "$HOME/.config/waybar" "$HOME/.config/hypr/conf" "$HOME/.config/nwg-drawer"
echo old > "$HOME/.config/waybar/config"; echo old > "$HOME/.config/hypr/conf/look.lua"; echo old > "$HOME/.config/nwg-drawer/drawer.css"
echo mine > "$HOME/.config/waybar/local.jsonc"
"${sync}"
expect "old waybar/config removed" '! test -e "$HOME/.config/waybar/config"'
expect "old conf dir removed" '! test -e "$HOME/.config/hypr/conf"'
expect "old nwg-drawer removed" '! test -e "$HOME/.config/nwg-drawer"'
expect "user local.jsonc untouched by retirement" 'test "$(cat "$HOME/.config/waybar/local.jsonc")" = mine'
expect "a retired file entry never removes a directory" 'printf ".config/waybar\n" > "$share/skel.retired"; mkdir -p "$HOME/.config/waybar"; echo x > "$share/stamp"; "$sync"; test -d "$HOME/.config/waybar"'

# 8b. a retired directory that is a symlink: the link is removed, its target is untouched
export HOME="$(mktemp -d)"; real="$(mktemp -d)"; echo keep > "${real}/mine.lua"
mkdir -p "$HOME/.config/hypr"; ln -s "${real}" "$HOME/.config/hypr/conf"
printf '.config/hypr/conf/\n' > "${share}/skel.retired"; echo r1 > "${share}/stamp"; "${sync}"
expect "retired symlinked dir: link removed" '! test -L "$HOME/.config/hypr/conf"'
expect "retired symlinked dir: target untouched" 'test -f "${real}/mine.lua"'
# 8c. malformed retire entries are refused and nothing is removed
export HOME="$(mktemp -d)"; mkdir -p "$HOME/.config/keep"; echo x > "$HOME/.config/keep/f"
printf '/\n.config/\n.config/../.bashrc\n/etc/passwd\nnotdotconfig/x\n' > "${share}/skel.retired"; echo r2 > "${share}/stamp"
rc=0; out="$("${sync}" 2>&1)" || rc=$?
expect "malformed retire entries are rejected" '[[ "$out" == *"refusing retired path"* ]]'
expect "home untouched after rejected entries" 'test -f "$HOME/.config/keep/f" && test -d "$HOME/.config"'
printf '' > "${share}/skel.retired"
# 8d. a deleted local file comes back on the next login even when the stamp is unchanged
export HOME="$(mktemp -d)"; "${sync}"; rm "$HOME/.config/waybar/local.jsonc"; "${sync}"
expect "deleted local file recreated without a stamp change" 'test -f "$HOME/.config/waybar/local.jsonc"'

# 9. theme unit ordered before the compositor and enabled for every user
unit_expect "theme unit enabled for every uwsm session instance" 'test -L /etc/systemd/user/wayland-session-pre@.target.wants/atomic-hyprland-theme@.service'
unit_expect "theme unit runs after dotfiles" 'grep -q "^After=atomic-hyprland-dotfiles.service" /usr/lib/systemd/user/atomic-hyprland-theme@.service'
unit_expect "theme unit runs before the session instance" 'grep -q "^Before=wayland-session-pre@%i.target" /usr/lib/systemd/user/atomic-hyprland-theme@.service'

# 10. ensure-theme renders on first login and is a no-op afterwards
export HOME="$(mktemp -d)" HYPR_THEME_SHARE="${share}" HYPR_THEME_NO_APPLY=1
# This section tests ensure-theme's logic, not the image's templates: use one toy template only.
rm -rf "${share}/themed"; mkdir -p "${share}/themes/t/backgrounds" "${share}/themed"
printf 'background = "#000000"\n' > "${share}/themes/t/colors.toml"; : > "${share}/themes/t/backgrounds/a.png"
echo 'x={{ background }}' > "${share}/themed/x.tpl"
HYPR_THEME_DEFAULT=t "${ensure}"
expect "ensure-theme rendered the default theme" 'test -f "$HOME/.config/atomic-hyprland/current/theme/x"'
expect "ensure-theme recorded the stamp" 'cmp -s "$share/stamp" "$HOME/.config/atomic-hyprland/current/.stamp"'
out="$(HYPR_THEME_DEFAULT=t "${ensure}")"
expect "ensure-theme no-op on same stamp" '[[ "$out" == *"up to date"* ]]'
# a chosen theme that no longer exists falls back to the default instead of failing every login
echo gone > "$HOME/.config/atomic-hyprland/current/theme.name"; echo again > "${share}/stamp"
rc=0; out="$(HYPR_THEME_DEFAULT=t "${ensure}" 2>&1)" || rc=$?
expect "ensure-theme falls back when the chosen theme is gone" 'test $rc = 0 && [[ "$out" == *"falling back"* ]]'
expect "ensure-theme fallback records the default" 'test "$(cat "$HOME/.config/atomic-hyprland/current/theme.name")" = t'
echo other > "${share}/stamp"; echo 'y={{ background }}' > "${share}/themed/y.tpl"
HYPR_THEME_DEFAULT=t "${ensure}"
expect "ensure-theme re-renders when the image stamp changes" 'test -f "$HOME/.config/atomic-hyprland/current/theme/y"'
expect "ensure-theme keeps the chosen theme name" 'test "$(cat "$HOME/.config/atomic-hyprland/current/theme.name")" = t'

exit "$fail"
