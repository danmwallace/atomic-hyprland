"""hypr-mcp: put the MCP registry into each agent's own config, and start servers.

  hypr-mcp sync         write the registry into Claude Code (user scope) and,
                        when Gemini CLI is present, ~/.gemini/settings.json
  hypr-mcp run <name>   resolve the server's secret references, exec it
  hypr-mcp list         show the merged registry

Every stdio server is written as `hypr-mcp run <name>`, so secrets are resolved
when the server starts and never land in an agent's config file. Names this
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
from .registry import ServerDef, load_registry
from .secrets import SecretError, resolve_env


def _warn(msg: str) -> None:
    print(f"hypr-mcp: {msg}", file=sys.stderr)


def client_entry(d: ServerDef) -> dict:
    if "command" in d.spec:
        return {"type": "stdio", "command": "hypr-mcp", "args": ["run", d.name]}
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


def gemini_entry(d: ServerDef) -> dict:
    if "command" in d.spec:
        return {"command": "hypr-mcp", "args": ["run", d.name]}
    entry = {"url": d.spec["url"]} if d.spec.get("type") == "sse" else {"httpUrl": d.spec["url"]}
    if d.spec.get("headers"):
        entry["headers"] = d.spec["headers"]
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
        servers[name] = gemini_entry(d)
        new_managed.add(name)
    _write_atomic(settings, json.dumps(data, indent=2) + "\n")
    return new_managed


def load_managed(path: Path) -> dict[str, set[str]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    return {k: set(data.get(k, [])) for k in ("claude", "gemini")}


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


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("sync", "run", "list"):
        print(__doc__.strip().split("\n\n")[0], file=sys.stderr)
        print("usage: hypr-mcp sync | run <name> | list", file=sys.stderr)
        return 2
    dirs = paths.registry_dirs()
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
            print(f"{name}\t{d.source}\tread-only: {ro}")
        return 0
    state = load_managed(paths.managed_file())
    if shutil.which("claude"):
        state["claude"] = sync_claude(defs, state["claude"])
    gemini_settings = Path(os.environ.get("HOME", "~")).expanduser() / ".gemini" / "settings.json"
    state["gemini"] = sync_gemini(defs, state["gemini"], gemini_settings)
    save_managed(paths.managed_file(), state)
    return 0
