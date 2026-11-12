"""The MCP drop-in registry: one JSON file per server in three folders.

/usr/share/atomic-hyprland/mcp.d (image), /etc/atomic-hyprland/mcp.d (machine)
and ~/.config/atomic-hyprland/mcp.d (user). A later folder replaces a
same-named file from an earlier one; {"disabled": true} switches a server off.
The file stem is the server name. Besides the usual MCP keys a file may carry:
  readOnlyTools  tools safe to run without asking (available in ask mode)
  toolNotes      tool -> how to undo it, shown on its approval card
  rootTools      tools that act as root; never "always allow"
"""
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_KEYS = ("readOnlyTools", "toolNotes", "rootTools", "disabled")


@dataclass
class ServerDef:
    name: str
    spec: dict
    read_only_tools: list[str] = field(default_factory=list)
    tool_notes: dict[str, str] = field(default_factory=dict)
    root_tools: list[str] = field(default_factory=list)
    source: Path | None = None


def _warn(msg: str) -> None:
    print(f"hypr-mcp: {msg}", file=sys.stderr)


def _parse(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        _warn(f"skipping {path}: {exc}")
        return None
    if not isinstance(data, dict):
        _warn(f"skipping {path}: not a JSON object")
        return None
    return data


def load_registry(dirs: list[Path]) -> dict[str, ServerDef]:
    raw: dict[str, tuple[dict, Path]] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.json")):
            data = _parse(path)
            if data is not None:
                raw[path.stem] = (data, path)

    servers: dict[str, ServerDef] = {}
    for name, (data, path) in sorted(raw.items()):
        if data.get("disabled") is True:
            continue
        spec = {k: v for k, v in data.items() if k not in REGISTRY_KEYS}
        if "command" not in spec and "url" not in spec:
            _warn(f"skipping {path}: needs \"command\" or \"url\"")
            continue
        servers[name] = ServerDef(
            name=name,
            spec=spec,
            read_only_tools=list(data.get("readOnlyTools", [])),
            tool_notes=dict(data.get("toolNotes", {})),
            root_tools=list(data.get("rootTools", [])),
            source=path,
        )
    return servers
