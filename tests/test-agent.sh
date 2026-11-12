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
exit "$fail"
