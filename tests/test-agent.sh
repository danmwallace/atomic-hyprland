#!/usr/bin/bash
# Host-side: bash tests/test-agent.sh (from the repo root)
# The agentic desktop: the atomic_agent package's unit tests (python3 unittest,
# no python3-mcp needed: server modules import mcp only inside main()), plus
# shell checks on the files that wire it into the image.
set -uo pipefail
fail=0
check() { if "$@" >/dev/null 2>&1; then echo "ok    $*"; else echo "FAIL  $*"; fail=1; fi; }

pylib="$PWD/files/usr/lib/atomic-hyprland/python"
export ATOMIC_AGENT_PYLIB="$pylib" PYTHONPATH="$pylib" PYTHONDONTWRITEBYTECODE=1
if python3 -m unittest discover -s tests/py -v 2>&1 | tee /dev/stderr | tail -1 | grep -qx OK; then
    echo "ok    python3 -m unittest discover -s tests/py"
else
    echo "FAIL  python3 -m unittest discover -s tests/py"; fail=1
fi
# hypr-mcp: the registry sync runs at login and whenever a registry folder changes
units=files/usr/lib/systemd/user
check test -x files/usr/bin/hypr-mcp
check grep -qx 'ExecStart=/usr/bin/hypr-mcp sync' $units/hypr-mcp-sync.service
check grep -qx 'PathChanged=/etc/atomic-hyprland/mcp.d' $units/hypr-mcp-sync.path
check grep -qx 'PathChanged=%h/.config/atomic-hyprland/mcp.d' $units/hypr-mcp-sync.path
check test -d files/etc/atomic-hyprland/mcp.d
check grep -q 'systemctl --global enable hypr-mcp-sync.service hypr-mcp-sync.path' build/40-finalize.sh
exit "$fail"
