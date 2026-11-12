#!/usr/bin/bash
# Host-side: bash tests/test-terminal.sh (from the repo root)
# hypr-terminal is the image's terminal: Ghostty where the GPU can run it, Alacritty
# where it cannot. Ghostty needs GLSL 4.30; Intel HD 4000 (Ivy Bridge, the T430)
# stops at 4.20 and Ghostty exits without a window. eglinfo, ghostty and alacritty
# are stubbed here, so this runs anywhere.
set -uo pipefail
fail=0
check() { if "$@" >/dev/null 2>&1; then echo "ok    $*"; else echo "FAIL  $*"; fail=1; fi; }

script=files/usr/bin/hypr-terminal
check test -x "$script"
check bash -n "$script"

stubs="$(mktemp -d)"
trap 'rm -rf "$stubs"' EXIT
for t in ghostty alacritty; do
    printf '#!/usr/bin/bash\necho %s "$@"\n' "$t" > "$stubs/$t"
done
# eglinfo prints the core-profile GLSL line for $GLSL; GLSL=fail exits non-zero with no output
cat > "$stubs/eglinfo" <<'EOF'
#!/usr/bin/bash
[[ "$GLSL" == fail ]] && exit 1
echo "EGL version string: 1.5"
echo "OpenGL core profile shading language version: $GLSL"
echo "OpenGL ES profile shading language version: OpenGL ES GLSL ES 3.00"
EOF
chmod +x "$stubs"/*

# run GLSL ARGS...: what hypr-terminal execs, with eglinfo reporting GLSL
run() { local g="$1"; shift; GLSL="$g" PATH="$stubs" "$BASH" "$script" "$@"; }
# without eglinfo on PATH at all
# "$BASH" is absolute: PATH holds only the stubs, so a bare bash would not resolve
run_no_egl() { mv "$stubs/eglinfo" "$stubs/eglinfo.off"; PATH="$stubs" "$BASH" "$script" "$@"; mv "$stubs/eglinfo.off" "$stubs/eglinfo"; }

check test "$(run 4.60)" = "ghostty"
check test "$(run 4.30)" = "ghostty"
check test "$(run 4.20 -e btop)" = "alacritty -e btop"
check test "$(run 3.30)" = "alacritty"
check test "$(run 4.60 -e nmtui)" = "ghostty -e nmtui"
# arguments with spaces survive intact
check test "$(run 4.20 -e sh -c 'echo a  b')" = "alacritty -e sh -c echo a  b"
# no answer from the GPU probe: keep the image default rather than guess old hardware
check test "$(run fail)" = "ghostty"
check bash -c "$(declare -f run_no_egl); stubs='$stubs' script='$script'; test \"\$(run_no_egl)\" = ghostty"

# Every launcher in the session goes through hypr-terminal, never ghostty directly.
share=files/usr/share/atomic-hyprland
check grep -qx 'local terminal = "hypr-terminal"' $share/hypr/binds.lua
check grep -qx 'hl.env("TERMINAL", "hypr-terminal")' $share/hypr/env.lua
check grep -qx 'export TERMINAL=hypr-terminal' files/etc/xdg/uwsm/env-hyprland
check grep -qx 'term=hypr-terminal' files/etc/skel/.config/wofi/config
check bash -c '! grep -nE "ghostty -e|\"ghostty\"|=ghostty$" '"$share"'/hypr/*.lua '"$share"'/waybar/config.jsonc files/etc/xdg/uwsm/env-hyprland files/etc/skel/.config/wofi/config'
check grep -qx egl-utils build/packages.txt
exit "$fail"
