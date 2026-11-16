"""The MCP drop-in registry: one JSON file per server in three folders.

/usr/share/atomic-hyprland/mcp.d (image), /etc/atomic-hyprland/mcp.d (machine)
and ~/.config/atomic-hyprland/mcp.d (user). A later folder replaces a
same-named file from an earlier one; {"disabled": true} switches a server off.
The file stem is the server name. Secrets are never stored in a file: an env
value (stdio) or a header value (url) may be a reference instead, {"credential":
N} or {"keyring": {...}}, resolved by hypr-mcp run / hypr-mcp headers.
Besides the usual MCP keys a file may carry:
  readOnlyTools  tools safe to run without asking (available in ask mode)
  toolNotes      tool -> how to undo it, shown on its approval card
  rootTools      tools that act as root; never "always allow"
  askEveryTime   tools that change something; a card (or a prompt) on every call,
                 never "always allow"
  denyTools      tools no agent may call (dropped from every client)
rootTools, askEveryTime and denyTools accumulate across the layers, and a root,
ask or denied tool is never read-only, so a later (user-writable) file cannot
quietly turn a root or ask action into one that runs without asking, or bring
back a denied tool. A layer may hold only these lists (no "command"/"url"): the
mcp_servers role writes a server's askEveryTime that way into the root-owned
/etc layer, so the user-writable entry can't drop it.
"""
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_KEYS = ("readOnlyTools", "toolNotes", "rootTools", "askEveryTime", "denyTools", "disabled")
ACCUMULATED_KEYS = ("rootTools", "askEveryTime", "denyTools")
_NOT_NAME = re.compile(r"[^A-Za-z0-9_-]")


def tool_rule(server: str, tool: str) -> str:
    """The name Claude Code gives an MCP tool, for allow/deny rules and card lookups.
    It replaces anything outside [A-Za-z0-9_-] with "_" in both parts; a rule built from
    the raw name ("home.lab") would never match, and a deny would silently fail open."""
    return f"mcp__{_NOT_NAME.sub('_', server)}__{_NOT_NAME.sub('_', tool)}"


@dataclass
class ServerDef:
    name: str
    spec: dict
    read_only_tools: list[str] = field(default_factory=list)
    tool_notes: dict[str, str] = field(default_factory=dict)
    root_tools: list[str] = field(default_factory=list)
    ask_tools: list[str] = field(default_factory=list)
    deny_tools: list[str] = field(default_factory=list)
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
    # A string would be read as its letters ("edit" denies e, d, i, t, not edit) and null
    # would crash every reader; skipping the file keeps the lower layers' rules.
    for key in ("readOnlyTools", "rootTools", "askEveryTime", "denyTools"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            _warn(f"skipping {path}: {key} must be a list of tool names")
            return None
    return data


def load_registry(dirs: list[Path]) -> dict[str, ServerDef]:
    raw: dict[str, tuple[dict, Path]] = {}
    root_tools: dict[str, list[str]] = {}
    ask_tools: dict[str, list[str]] = {}
    deny_tools: dict[str, list[str]] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.json")):
            data = _parse(path)
            if data is not None:
                # A layer holding only accumulating lists adds to them and leaves the
                # definition from a lower layer in place.
                if not set(data) <= set(ACCUMULATED_KEYS) or path.stem not in raw:
                    raw[path.stem] = (data, path)
                for key, store in zip(ACCUMULATED_KEYS, (root_tools, ask_tools, deny_tools)):
                    acc = store.setdefault(path.stem, [])
                    acc += [t for t in data.get(key, []) if t not in acc]

    servers: dict[str, ServerDef] = {}
    for name, (data, path) in sorted(raw.items()):
        if data.get("disabled") is True:
            continue
        spec = {k: v for k, v in data.items() if k not in REGISTRY_KEYS}
        if "command" not in spec and "url" not in spec:
            _warn(f"skipping {path}: needs \"command\" or \"url\"")
            continue
        roots = root_tools.get(name, [])
        asks = ask_tools.get(name, [])
        denied = deny_tools.get(name, [])
        servers[name] = ServerDef(
            name=name,
            spec=spec,
            read_only_tools=[t for t in data.get("readOnlyTools", [])
                             if t not in roots and t not in asks and t not in denied],
            tool_notes=dict(data.get("toolNotes", {})),
            root_tools=list(roots),
            ask_tools=list(asks),
            deny_tools=list(denied),
            source=path,
        )
    return servers
