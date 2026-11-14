"""hypr-mcp: put the MCP registry into each agent's own config, and start servers.

  hypr-mcp sync         write the registry into Claude Code (user scope; denyTools
                        become deny rules in its user settings) and, when Gemini
                        CLI is present, ~/.gemini/settings.json (denyTools become
                        excludeTools)
  hypr-mcp run <name>   resolve the server's secret references, exec it
  hypr-mcp headers <name>
                        print a url server's headers as JSON, secrets resolved
                        (Claude Code's headersHelper for that server)
  hypr-mcp list         show the merged registry

Every stdio server is written as `hypr-mcp run <name>`, so secrets are resolved
when the server starts and never land in an agent's config file. A url server
whose headers hold a secret reference is written with a headersHelper instead
of its headers, so Claude Code fetches them at connect time; Gemini CLI has no
equivalent and gets no entry for it. Names this
tool wrote are remembered in ~/.local/state/atomic-hyprland/mcp-managed.json;
a server the user added by hand under the same name is left alone.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import paths
from .registry import ServerDef, load_registry, tool_rule
from .secrets import SecretError, resolve_env


def _warn(msg: str) -> None:
    print(f"hypr-mcp: {msg}", file=sys.stderr)


def has_secret_headers(d: ServerDef) -> bool:
    return any(isinstance(v, dict) for v in (d.spec.get("headers") or {}).values())


def client_entry(d: ServerDef) -> dict:
    if "command" in d.spec:
        return {"type": "stdio", "command": "hypr-mcp", "args": ["run", d.name]}
    if has_secret_headers(d):
        entry = {k: v for k, v in d.spec.items() if k != "headers"}
        entry["headersHelper"] = f"hypr-mcp headers {d.name}"
        return entry
    return dict(d.spec)


def sync_claude(defs: dict[str, ServerDef], managed: set[str], run=subprocess.run) -> set[str]:
    def claude(*args):
        return run(["claude", "mcp", *args], capture_output=True, text=True)

    new_managed: set[str] = set()
    for name, d in sorted(defs.items()):
        exists = claude("get", name).returncode == 0
        if exists and name not in managed:
            _warn(f"Claude Code already has a server named {name!r} that hypr-mcp did not add; leaving it")
            continue
        if exists:
            claude("remove", "--scope", "user", name)
        if claude("add-json", "--scope", "user", name, json.dumps(client_entry(d))).returncode == 0:
            new_managed.add(name)
        else:
            _warn(f"claude mcp add-json {name} failed")
    for name in sorted(managed - set(defs)):
        claude("remove", "--scope", "user", name)
    return new_managed


def gemini_entry(d: ServerDef) -> dict | None:
    """None for a url server with secret headers: Gemini CLI can't fetch them."""
    if has_secret_headers(d):
        return None
    if "command" in d.spec:
        entry = {"command": "hypr-mcp", "args": ["run", d.name]}
    else:
        entry = {"url": d.spec["url"]} if d.spec.get("type") == "sse" else {"httpUrl": d.spec["url"]}
        if d.spec.get("headers"):
            entry["headers"] = d.spec["headers"]
    if d.deny_tools:
        entry["excludeTools"] = list(d.deny_tools)
    return entry


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def sync_gemini(defs: dict[str, ServerDef], managed: set[str], settings: Path) -> set[str]:
    if not shutil.which("gemini") and not settings.parent.is_dir():
        return set()
    try:
        data = json.loads(settings.read_text()) if settings.exists() else {}
    except ValueError as exc:
        _warn(f"not touching {settings}: {exc}")
        return managed
    servers = data.setdefault("mcpServers", {})
    for name in managed - set(defs):
        servers.pop(name, None)
    new_managed: set[str] = set()
    for name, d in sorted(defs.items()):
        if name in servers and name not in managed:
            _warn(f"Gemini CLI already has a server named {name!r} that hypr-mcp did not add; leaving it")
            continue
        entry = gemini_entry(d)
        if entry is None:
            if name in managed:
                servers.pop(name, None)
            _warn(f"Gemini CLI can't fetch secret headers; leaving out {name}")
            continue
        servers[name] = entry
        new_managed.add(name)
    _write_atomic(settings, json.dumps(data, indent=2) + "\n")
    return new_managed


def claude_settings_path() -> Path:
    """Claude Code's user settings: $CLAUDE_CONFIG_DIR/settings.json, else ~/.claude/settings.json."""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(cfg) if cfg else Path(os.environ.get("HOME", "~")).expanduser() / ".claude"
    return base / "settings.json"


def deny_rules(defs: dict[str, ServerDef]) -> set[str]:
    return {tool_rule(d.name, t) for d in defs.values() for t in d.deny_tools}


def sync_claude_rules(settings: Path, kind: str, wanted: set[str], managed: set[str]) -> set[str]:
    """Keep hypr-mcp's rules in permissions.<kind> of Claude Code's user settings and
    return the rules it now manages. Only rules it added are ever removed; a rule the
    user wrote is left alone and not taken over. Other keys are untouched (claude-config's
    apply merges its own keys into the same file). The file's mode is kept, since it can
    hold secrets; a new file is 0600. A file that isn't valid JSON is left as it is."""
    try:
        data = json.loads(settings.read_text()) if settings.exists() else {}
    except (OSError, ValueError) as exc:
        _warn(f"not touching {settings}: {exc}")
        return managed
    perms = data.get("permissions", {}) if isinstance(data, dict) else None
    current = perms.get(kind, []) if isinstance(perms, dict) else None
    if not isinstance(current, list):
        _warn(f"not touching {settings}: permissions.{kind} is not a list")
        return managed
    add = wanted - set(current)
    drop = managed - wanted
    new = [r for r in current if r not in drop] + sorted(add)
    if new != current:
        mode = settings.stat().st_mode & 0o777 if settings.exists() else 0o600
        data.setdefault("permissions", perms)[kind] = new
        _write_atomic(settings, json.dumps(data, indent=2) + "\n")
        os.chmod(settings, mode)
    return (managed & wanted) | add


def load_managed(path: Path) -> dict[str, set[str]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    return {k: set(data.get(k, [])) for k in ("claude", "gemini", "claude_deny")}


def save_managed(path: Path, managed: dict[str, set[str]]) -> None:
    _write_atomic(path, json.dumps({k: sorted(v) for k, v in managed.items()}) + "\n")


def run_server(name: str, dirs: list[Path]) -> None:
    d = load_registry(dirs).get(name)
    if d is None or "command" not in d.spec:
        _warn(f"no stdio server named {name!r} in the registry")
        sys.exit(2)
    try:
        env = {**os.environ, **resolve_env(d.spec.get("env", {}))}
    except SecretError as exc:
        _warn(f"{name}: {exc}")
        sys.exit(3)
    cmd = d.spec["command"]
    os.execvpe(cmd, [cmd, *d.spec.get("args", [])], env)


def print_headers(name: str, dirs: list[Path]) -> int:
    """hypr-mcp headers <name>: the headers as one JSON object on stdout. A failed
    lookup prints nothing there (the client then gets no headers) and names only
    the header on stderr, never a value."""
    d = load_registry(dirs).get(name)
    if d is None or "url" not in d.spec:
        _warn(f"no url server named {name!r} in the registry")
        return 2
    try:
        headers = resolve_env(d.spec.get("headers") or {})
    except SecretError as exc:
        _warn(f"{name}: {exc}")
        return 3
    print(json.dumps(headers))
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("sync", "run", "list", "headers"):
        print(__doc__.strip().split("\n\n")[0], file=sys.stderr)
        print("usage: hypr-mcp sync | run <name> | headers <name> | list", file=sys.stderr)
        return 2
    dirs = paths.registry_dirs()
    if argv[0] == "headers":
        if len(argv) != 2:
            print("usage: hypr-mcp headers <name>", file=sys.stderr)
            return 2
        return print_headers(argv[1], dirs)
    if argv[0] == "run":
        if len(argv) != 2:
            print("usage: hypr-mcp run <name>", file=sys.stderr)
            return 2
        run_server(argv[1], dirs)
        return 0
    defs = load_registry(dirs)
    if argv[0] == "list":
        for name, d in defs.items():
            ro = ",".join(d.read_only_tools) or "-"
            deny = ",".join(d.deny_tools) or "-"
            print(f"{name}\t{d.source}\tread-only: {ro}\tdeny: {deny}")
        return 0
    state = load_managed(paths.managed_file())
    if shutil.which("claude"):
        state["claude"] = sync_claude(defs, state["claude"])
        state["claude_deny"] = sync_claude_rules(claude_settings_path(), "deny", deny_rules(defs), state["claude_deny"])
    gemini_settings = Path(os.environ.get("HOME", "~")).expanduser() / ".gemini" / "settings.json"
    state["gemini"] = sync_gemini(defs, state["gemini"], gemini_settings)
    save_managed(paths.managed_file(), state)
    return 0
