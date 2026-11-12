"""Undo for the agent's file changes.

Before an edit tool touches a file, the PreToolUse hook copies the original
into the session folder: manifest.jsonl lists {"path", "existed", "copy"} in
order, copies live in files/<n>. After the tool ran, the PostToolUse hook adds
{"event": "applied", "path"}: only applied entries count as changes, so a
denied or failed edit is never "undone" over the user's own later work. Only
the first snapshot of a path counts, so undo returns it to how it was before
the session. /etc is not edited this way at all: the system server's
write_etc_file goes through the root helper, which keeps the same manifest.
"""
import json
import os
import shutil
import sys
from pathlib import Path

from . import paths
from .policy import EDIT_TOOLS

UNDONE = {"event": "undone"}


def _entries(sdir: Path) -> list[dict]:
    m = sdir / "manifest.jsonl"
    if not m.exists():
        return []
    return [json.loads(line) for line in m.read_text().splitlines() if line.strip()]


def _append(sdir: Path, entry: dict) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    with open(sdir / "manifest.jsonl", "a") as m:
        m.write(json.dumps(entry) + "\n")


def is_etc(path: Path | str) -> bool:
    return str(path) == "/etc" or str(path).startswith("/etc/")


def snapshot(sdir: Path, path: Path) -> None:
    path = Path(os.path.abspath(path))
    entries = _entries(sdir)
    if any(e.get("path") == str(path) and "existed" in e for e in entries):
        return
    (sdir / "files").mkdir(parents=True, exist_ok=True)
    if path.exists():
        copy = f"files/{sum(1 for e in entries if 'existed' in e)}"
        shutil.copy2(path, sdir / copy)
        _append(sdir, {"path": str(path), "existed": True, "copy": copy})
    else:
        _append(sdir, {"path": str(path), "existed": False, "copy": None})


def mark_applied(sdir: Path, path: Path | str) -> None:
    path = os.path.abspath(path)
    entries = _entries(sdir)
    if not any(e.get("path") == path and "existed" in e for e in entries):
        return
    if any(e == {"event": "applied", "path": path} for e in entries):
        return
    _append(sdir, {"event": "applied", "path": path})


def changed(sdir: Path) -> list[str]:
    """Paths the agent actually changed this session, in order; [] once undone."""
    entries = _entries(sdir)
    if UNDONE in entries:
        return []
    applied = {e["path"] for e in entries if e.get("event") == "applied"}
    return [e["path"] for e in entries if "existed" in e and e["path"] in applied]


def _restore_etc_unset(path: str, copy: str | None) -> None:
    raise OSError(f"no root helper to restore {path}")


def undo(sdir: Path, restore_etc=_restore_etc_unset) -> list[str]:
    entries = _entries(sdir)
    todo = set(changed(sdir))
    if not todo:
        return []
    restored: list[str] = []
    for e in reversed([e for e in entries if "existed" in e and e["path"] in todo]):
        path, copy = e["path"], (str(sdir / e["copy"]) if e.get("copy") else None)
        if is_etc(path):
            restore_etc(path, copy)
        elif e["existed"]:
            shutil.copy2(copy, path)
        elif os.path.lexists(path):
            os.unlink(path)
        restored.append(path)
    _append(sdir, UNDONE)
    return restored


def _target(event: dict) -> str | None:
    tool_input = event.get("tool_input") or {}
    return tool_input.get("file_path") or tool_input.get("notebook_path")


def hook_pre_tool_use(event: dict) -> int:
    """Claude Code PreToolUse hook. 0 lets the tool run; 2 blocks it (stderr says why).
    Fails closed: if the copy for undo cannot be saved, the edit does not happen."""
    try:
        if event.get("tool_name") not in EDIT_TOOLS:
            return 0
        target = _target(event)
        if not target:
            return 0
        if is_etc(target):
            print("hypr-agent: files under /etc are written with mcp__system__write_etc_file "
                  "(it asks after the approval card and keeps a copy for undo), not Edit/Write.", file=sys.stderr)
            return 2
        snapshot(paths.session_dir(event["session_id"]), Path(target))
        return 0
    except Exception as exc:  # noqa: BLE001 - any failure blocks the edit
        print(f"hypr-agent: not editing: could not save a copy for undo ({exc!r})", file=sys.stderr)
        return 2


def hook_post_tool_use(event: dict) -> int:
    """Claude Code PostToolUse hook: the edit ran, so it counts as a change."""
    try:
        if event.get("tool_name") in EDIT_TOOLS and _target(event):
            mark_applied(paths.session_dir(event["session_id"]), _target(event))
    except Exception as exc:  # noqa: BLE001 - never fail the tool after the fact
        print(f"hypr-agent: could not record the change ({exc!r})", file=sys.stderr)
    return 0
