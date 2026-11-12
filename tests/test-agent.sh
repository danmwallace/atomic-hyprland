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
check test -x files/usr/libexec/atomic-hyprland/mcp-server
check python3 -m py_compile tests/mcp-smoke.py
# root helper: a fixed set of operations behind polkit auth_admin_keep
pol=files/usr/share/polkit-1/actions/org.atomic-hyprland.agent.policy
check test -x files/usr/libexec/atomic-hyprland/agent-root
check python3 -c "import sys, xml.dom.minidom; xml.dom.minidom.parse(sys.argv[1])" $pol  # xmllint is not on every runner
check grep -q '<annotate key="org.freedesktop.policykit.exec.path">/usr/libexec/atomic-hyprland/agent-root</annotate>' $pol
check bash -c "grep -c '>auth_admin_keep<' $pol | grep -qx 3"
check bash -c '! grep -qE "^(from|import) atomic_agent|sys.path" files/usr/libexec/atomic-hyprland/agent-root'
# agent cards are plain text: no markup that could hide the real command
check bash -c "grep -A1 -x '\[app-name=hypr-agent\]' files/usr/share/atomic-hyprland/mako/core.ini | grep -qx markup=0"
check bash -c "awk '/^\\[app-name=hypr-agent\\]/{s=1;next} /^\\[/{s=0} s && /^height=320$/{f=1} END{exit !f}' files/usr/share/atomic-hyprland/mako/core.ini"
# the image's source repo is set once and feeds both the label and the PR target
check grep -qx 'ARG IMAGE_SOURCE=https://github.com/danmwallace/atomic-hyprland' Containerfile
check grep -q 'org.opencontainers.image.source="${IMAGE_SOURCE}"' Containerfile
check grep -q '40-finalize.sh "${IMAGE_VERSION}" "${IMAGE_SOURCE}"' Containerfile
check grep -q '/usr/share/atomic-hyprland/image-source' build/40-finalize.sh
exit "$fail"
