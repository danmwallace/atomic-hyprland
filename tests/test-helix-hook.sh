#!/usr/bin/bash
# Host-side: bash tests/test-helix-hook.sh (from the repo root)
# The shipped theme hook that points Helix at the theme's counterpart
# (apps.toml's helix value) by writing ~/.config/helix/themes/atomic-hyprland.toml,
# then asks running editors to reload (SIGUSR1). hx and pkill are stubs; PATH
# holds only the stubs and the few tools the hook needs, so "no hx" is real.
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
hook="$PWD/files/usr/share/atomic-hyprland/hooks/theme-set.d/40-helix"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
theme_file="$work/home/.config/helix/themes/atomic-hyprland.toml"

# fresh [apps.toml contents]: a new HOME and state; with an argument, a rendered apps.toml.
fresh() {
    rm -rf "${work:?}"/*
    mkdir -p "$work/home" "$work/stubs" "$work/bin" "$work/state/current/theme"
    [[ $# -gt 0 ]] && printf '%s\n' "$1" > "$work/state/current/theme/apps.toml"
    for t in sed head mkdir mv cat id mktemp rm dirname grep; do ln -s "$(command -v "$t")" "$work/bin/$t"; done
    printf '#!/bin/sh\nexit 0\n' > "$work/stubs/hx"
    printf '#!/bin/sh\necho "pkill $*" >> "%s/log"\nexit ${PKILL_RC:-0}\n' "$work" > "$work/stubs/pkill"
    chmod +x "$work/stubs/"*
}
run() { HOME="$work/home" HYPR_THEME_STATE="$work/state" PATH="$work/stubs:$work/bin" "$BASH" "$hook" fixture; }

check test -x "$hook"
check bash -n "$hook"

# mapped: the theme file inherits the mapped theme; running editors get SIGUSR1
fresh 'helix = "tokyonight"'
check run
check test "$(cat "$theme_file")" = 'inherits = "tokyonight"'
check grep -q -- '-USR1' "$work/log"
check grep -q -- '-x hx' "$work/log"

# real Helix names with '-' or '+' (nord-night, penumbra+) are kept, not refused
for ok in nord-night penumbra+ kanagawa-dragon; do
    fresh "helix = \"$ok\""
    check run
    check test "$(cat "$theme_file")" = "inherits = \"$ok\""
done

# no apps.toml (a user theme): fall back to the terminal palette
fresh
check run
check test "$(cat "$theme_file")" = 'inherits = "base16_terminal"'

# bad values are refused, not written
for bad in 'helix = "../../etc"' 'helix = "a b"' 'helix = "Tokyo/Night"' 'helix = ""'; do
    fresh "$bad"
    check run
    check test "$(cat "$theme_file")" = 'inherits = "base16_terminal"'
done

# Helix not installed: nothing written, still success
fresh 'helix = "nord"'
rm "$work/stubs/hx"
check run
check test ! -e "$theme_file"

# no running editor (pkill exits 1): still success, file still written
fresh 'helix = "nord"'
check bash -c "PKILL_RC=1 HOME='$work/home' HYPR_THEME_STATE='$work/state' PATH='$work/stubs:$work/bin' '$BASH' '$hook' fixture"
check test "$(cat "$theme_file")" = 'inherits = "nord"'

# the user's own config is never touched
fresh 'helix = "nord"'
mkdir -p "$work/home/.config/helix"
printf 'theme = "atomic-hyprland"\n[editor]\nline-number = "relative"\n' > "$work/home/.config/helix/config.toml"
cp "$work/home/.config/helix/config.toml" "$work/config.before"
check run
check cmp "$work/config.before" "$work/home/.config/helix/config.toml"

exit "$fail"
