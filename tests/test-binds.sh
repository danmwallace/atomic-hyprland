#!/usr/bin/bash
# Host-side: bash tests/test-binds.sh (from the repo root)
# Hyprland fires every bind that matches a combo and matches keysyms case-insensitively,
# so two binds on the same combo (SUPER+L vs SUPER+l) both run. None may collide.
set -uo pipefail
fail=0
check() { if "$@" >/dev/null 2>&1; then echo "ok    $*"; else echo "FAIL  $*"; fail=1; fi; }

binds=files/usr/share/atomic-hyprland/hypr/binds.lua
# Expand the generated loops the same way Lua does: focus letters/arrows, workspaces 1..10.
combos="$(python3 - "$binds" <<'PY'
import re,sys
src=open(sys.argv[1]).read()
out=[]
for m in re.finditer(r'hl\.bind\((.+?),\s*hl\.', src):
    expr=m.group(1).strip()
    if expr.startswith('mod .. " + " .. pair[1]'):
        out += ["SUPER + "+k for k in ["left","right","up","down","h","l","k","j"]]
    elif 'mod .. " + " .. key' in expr:
        out += ["SUPER + "+str(k) for k in range(10)]
    elif 'mod .. " + SHIFT + " .. key' in expr:
        out += ["SUPER + SHIFT + "+str(k) for k in range(10)]
    elif 'mod .. " + CTRL + SHIFT + " .. key' in expr:
        out += ["SUPER + CTRL + SHIFT + "+str(k) for k in range(10)]
    else:
        s=expr.replace('mod .. ','"SUPER').replace('" + ','" + ').strip()
        s=re.sub(r'^"SUPER"\s*\+?\s*"? \+ ', 'SUPER + ', s) if s.startswith('"SUPER"') else s
        s=s.replace('"','')
        if s.startswith('SUPER + '): pass
        out.append(s.strip())
norm=lambda c: " + ".join(sorted(p.strip().lower() for p in c.split("+")))
seen={}
for c in out:
    n=norm(c); seen.setdefault(n,[]).append(c)
dups={k:v for k,v in seen.items() if len(v)>1}
for k,v in dups.items(): print("DUP", k, "<-", v)
print("TOTAL", len(out))
PY
)"
echo "$combos" | grep -E "^(DUP|TOTAL)" | head -12
check bash -c '! grep -q "^DUP" <<< "$1"' _ "$combos"
check bash -c 'grep -qE "^TOTAL [5-9][0-9]$" <<< "$1"' _ "$combos"
# the laptop keys and the lid lock exist
for k in XF86AudioRaiseVolume XF86AudioLowerVolume XF86AudioMute XF86AudioMicMute XF86MonBrightnessUp XF86MonBrightnessDown "switch:on:Lid Switch"; do
    check grep -q "\"$k\"" "$binds"
done
# programs start through uwsm-app so they get their own systemd scope (and survive a compositor crash cleanly)
check grep -q 'uwsm-app -- ' "$binds"
check bash -c '! grep -E "exec_cmd\((terminal|browser|fileManager|menu)\)" '"$binds"
exit "$fail"
