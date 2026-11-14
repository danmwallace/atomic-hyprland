#!/usr/bin/bash
# Host-side: bash tests/test-browser.sh (from the repo root)
# hypr-browser is $BROWSER: it starts Chromium detached and returns at once.
# Tools that launch $BROWSER and wait for it (gh auth login -w polls for the
# token only after the browser command returns) would otherwise hang until
# Chromium quits, whenever Chromium wasn't already running. chromium-browser is
# stubbed here (it stays up for 5 s), so this runs anywhere.
set -uo pipefail
fail=0
check() { if "$@" >/dev/null 2>&1; then echo "ok    $*"; else echo "FAIL  $*"; fail=1; fi; }

script=files/usr/bin/hypr-browser
check test -x "$script"
check bash -n "$script"

stubs="$(mktemp -d)"
trap 'rm -rf "$stubs"' EXIT
cat > "$stubs/chromium-browser" <<STUB
#!/usr/bin/bash
echo "\$@" > "$stubs/args"
sleep 5
STUB
chmod +x "$stubs/chromium-browser"

start=$(date +%s%N)
PATH="$stubs:/usr/bin:/bin" "$BASH" "$script" "https://github.com/login/device"
rc=$?
elapsed_ms=$(( ($(date +%s%N) - start) / 1000000 ))
check test "$rc" -eq 0
# Returns long before the 5 s browser stub exits.
check test "$elapsed_ms" -lt 2000
# The browser still got the URL.
for _ in $(seq 20); do [[ -s "$stubs/args" ]] && break; sleep 0.1; done
check grep -qx "https://github.com/login/device" "$stubs/args"

exit "$fail"
