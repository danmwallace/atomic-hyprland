"""Undo for the agent's file changes.

Before an edit tool touches a file, the PreToolUse hook copies the original
into the session folder: manifest.jsonl lists {"path", "existed", "copy"} in
order, copies live in files/<n>. Only the first snapshot of a path counts, so
undo returns it to how it was before the session. Paths under /etc are
snapshotted and restored by the root helper (pkexec agent-root).
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
    with open(sdir / "manifest.jsonl", "a") as m:
        m.write(json.dumps(entry) + "\n")


def is_etc(path: Path | str) -> bool:
    return str(path) == "/etc" or str(path).startswith("/etc/")


def snapshot(sdir: Path, path: Path) -> None:
    path = Path(os.path.abspath(path))
    entries = _entries(sdir)
    if any(e.get("path") == str(path) for e in entries):
        return
    (sdir / "files").mkdir(parents=True, exist_ok=True)
    if path.exists():
        copy = f"files/{sum(1 for e in entries if 'path' in e)}"
        shutil.copy2(path, sdir / copy)
        _append(sdir, {"path": str(path), "existed": True, "copy": copy})
    else:
        _append(sdir, {"path": str(path), "existed": False, "copy": None})


def _restore_etc_unset(path: str, copy: str | None) -> None:
    raise OSError(f"no root helper to restore {path}")


def undo(sdir: Path, restore_etc=_restore_etc_unset) -> list[str]:
    entries = _entries(sdir)
    if not entries or UNDONE in entries:
        return []
    restored: list[str] = []
    for e in reversed([e for e in entries if "path" in e]):
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


def _snapshot_etc_unset(sdir: Path, path: str) -> None:
    raise OSError(f"no root helper to snapshot {path}")


def hook_pre_tool_use(event: dict, snapshot_etc=_snapshot_etc_unset) -> int:
    """Claude Code PreToolUse hook. 0 lets the tool run; 2 blocks it (stderr says why)."""
    if event.get("tool_name") not in EDIT_TOOLS:
        return 0
    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return 0
    sdir = paths.session_dir(event["session_id"])
    try:
        if is_etc(target):
            snapshot_etc(sdir, target)
        else:
            snapshot(sdir, Path(target))
    except OSError as exc:
        print(f"hypr-agent: not editing {target}: could not save a copy for undo ({exc})", file=sys.stderr)
        return 2
    return 0
