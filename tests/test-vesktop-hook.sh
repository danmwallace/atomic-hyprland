#!/usr/bin/bash
# Host-side: bash tests/test-vesktop-hook.sh (from the repo root)
# The shipped theme hook that points Vesktop at the theme's counterpart: it owns
# one local theme file, themes/atomic-hyprland.css, which @imports apps.toml's
# pinned vesktop URL (Midnight also gets the theme's accent). Vencord reloads a
# changed local theme live, so the hook sends nothing to Vesktop.
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
hook="$PWD/files/usr/share/atomic-hyprland/hooks/theme-set.d/41-vesktop"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
vdir="$work/home/.var/app/dev.vencord.Vesktop/config/vesktop"
css="$vdir/themes/atomic-hyprland.css"
url='https://cdn.jsdelivr.net/gh/catppuccin/discord@0d8c7aaea33c655bb9e4c93d352a28f3baa69a75/dist/catppuccin-mocha.theme.css'
tagged='https://cdn.jsdelivr.net/gh/rose-pine/discord@v0.0.1/dist/rose-pine.css'
midnight='https://cdn.jsdelivr.net/gh/refact0r/midnight-discord@e8d9b43c151450219fae8c009af3e82b8f495575/build/midnight.css'

# fresh [apps.toml contents]: a new HOME (Vesktop configured) and state with a rendered theme.
fresh() {
    rm -rf "${work:?}"/*
    mkdir -p "$work/state/current/theme" "$vdir/settings"
    printf 'background = "#0a0a0a"\naccent = "#ff2a3d"\n' > "$work/state/current/theme/colors.toml"
    [[ $# -gt 0 ]] && printf '%s\n' "$1" > "$work/state/current/theme/apps.toml"
    printf '{"enabledThemes":["atomic-hyprland.css"],"useQuickCss":true}\n' > "$vdir/settings/settings.json"
    printf '/* mine */\n' > "$vdir/settings/quickCss.css"
}
run() { HOME="$work/home" HYPR_THEME_STATE="$work/state" "$BASH" "$hook" fixture; }

check test -x "$hook"
check bash -n "$hook"

# mapped URL: the file is exactly the import
fresh "vesktop = \"$url\""
check run
check test "$(cat "$css")" = "@import url(\"$url\");"

# a numeric tag counts as pinned
fresh "vesktop = \"$tagged\""
check run
check test "$(cat "$css")" = "@import url(\"$tagged\");"

# Midnight: the import plus the theme's accent in all five accent variables
fresh "vesktop = \"$midnight\""
check run
check grep -qxF "@import url(\"$midnight\");" "$css"
for i in 1 2 3 4 5; do check grep -qE "^ *--accent-$i: #ff2a3d;" "$css"; done

# Vesktop never configured on this machine: nothing written, success
fresh "vesktop = \"$url\""
rm -rf "$work/home/.var"
check run
check test ! -e "$css"

# no apps.toml (a user theme) or an empty value: the file is removed, success
fresh "vesktop = \"$url\""; run; rm "$work/state/current/theme/apps.toml"
check run
check test ! -e "$css"
fresh 'vesktop = ""'
check run
check test ! -e "$css"

# refused values: not https, unpinned branch, characters that could break out of url("")
for bad in 'http://cdn.jsdelivr.net/gh/a/b@1234567/x.css' \
           'https://cdn.jsdelivr.net/gh/a/b@main/x.css' \
           'https://cdn.jsdelivr.net/gh/a/b@master/x.css' \
           'https://raw.githubusercontent.com/a/b/refs/heads/main/x.css' \
           'https://x.example/a@1/x.css");@import url("https://evil.example/y.css' \
           'https://x.example/a@1/x.css;' \
           'https://x.example/a@1/x .css' \
           'https://cdn.jsdelivr.net/gh/a/b/x.css' \
           'https://cdn.jsdelivr.net/gh/a/b@latest/x.css' \
           'https://cdn.jsdelivr.net/gh/a/b@dev/x.css' \
           'https://raw.githubusercontent.com/a/b/main/x.css' \
           'https://catppuccin.github.io/discord/dist/x.css'; do
    fresh "vesktop = \"$bad\""
    check run
    check test ! -e "$css"
done

# Vesktop's own settings and the user's Quick CSS are never touched
fresh "vesktop = \"$midnight\""
cp "$vdir/settings/settings.json" "$work/settings.before"; cp "$vdir/settings/quickCss.css" "$work/quick.before"
check run
check cmp "$work/settings.before" "$vdir/settings/settings.json"
check cmp "$work/quick.before" "$vdir/settings/quickCss.css"

exit "$fail"
