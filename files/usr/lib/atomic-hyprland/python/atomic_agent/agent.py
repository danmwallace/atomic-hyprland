"""hypr-agent: Super+A asks a read-only agent about the screen; Fix it lets it
work in the background behind approval cards. See the design in
docs/superpowers/specs/2026-11-11-agentic-desktop-design.md.

Every session runs Claude Code headless with its own settings
(--setting-sources project,local, so ~/.claude/settings.json permissions never
apply), its own MCP servers (--strict-mcp-config) and a snapshot hook for undo.
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import paths, ui
from .context import Context, capture, prompt
from .mcp_sync import client_entry
from .registry import ServerDef, load_registry

SHARE = Path(os.environ.get("ATOMIC_AGENT_DATA", "/usr/share/atomic-hyprland/agent"))
MCP_SERVER = "/usr/libexec/atomic-hyprland/mcp-server"
HOOK = "hypr-agent hook pre-tool-use"
# Claude Code waits this long for an MCP tool; an approval waits up to 10 minutes.
MCP_TOOL_TIMEOUT_MS = "660000"


def build_settings(base: dict, rules_path: Path, registry: dict[str, ServerDef]) -> dict:
    settings = json.loads(json.dumps(base))
    perms = settings.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    for d in registry.values():
        allow += [f"mcp__{d.name}__{t}" for t in d.read_only_tools]
    try:
        allow += json.loads(rules_path.read_text()).get("permissions", {}).get("allow", [])
    except (OSError, ValueError):
        pass
    perms["allow"] = list(dict.fromkeys(allow))
    perms["defaultMode"] = "default"
    settings["hooks"] = {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit",
                                          "hooks": [{"type": "command", "command": HOOK}]}]}
    return settings


def mcp_config(registry: dict[str, ServerDef]) -> dict:
    servers = {name: client_entry(d) for name, d in registry.items()}
    servers["approvals"] = {"type": "stdio", "command": MCP_SERVER, "args": ["approvals"]}
    return {"mcpServers": servers}


def agent_env(sid: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env.update(HYPR_AGENT_SESSION=sid, MCP_TOOL_TIMEOUT=MCP_TOOL_TIMEOUT_MS)
    return env


def system_prompt_file(sid: str, instructions: Path | None = None) -> Path:
    """instructions.md, then the user's ~/.claude/CLAUDE.md (dropped by the isolated setting sources)."""
    parts = [(instructions or SHARE / "instructions.md").read_text()]
    user_md = Path(os.environ.get("HOME", "~")).expanduser() / ".claude" / "CLAUDE.md"
    if user_md.is_file():
        parts.append("# The user's own instructions (~/.claude/CLAUDE.md)\n\n" + user_md.read_text())
    f = paths.session_dir(sid) / "system-prompt.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n\n".join(parts))
    return f


def _isolation(settings_file: Path, mcp_file: Path, prompt_file: Path) -> list[str]:
    return ["--setting-sources", "project,local", "--settings", str(settings_file),
            "--mcp-config", str(mcp_file), "--strict-mcp-config",
            "--append-system-prompt-file", str(prompt_file)]


def ask_prompt(text: str, ctx: Context) -> str:
    lines = [text, "", "Context from the desktop (attached by the user):"]
    if ctx.screenshot:
        lines.append(f"- Screenshot of the focused window: {ctx.screenshot} (Read it first).")
    if ctx.clipboard:
        lines += ["- Clipboard:", "```", ctx.clipboard, "```"]
    if ctx.cwd:
        lines.append(f"- Working folder of the focused terminal: {ctx.cwd}")
    lines += ["", "This is ask mode: investigate and explain, but change nothing. If a fix is needed, "
              "say exactly what you would change; the user can then press Fix it."]
    return "\n".join(lines)


def ask_argv(sid: str, text: str, ctx: Context, settings_file: Path, mcp_file: Path, prompt_file: Path) -> list[str]:
    return ["claude", "-p", "--session-id", sid, "--output-format", "json",
            *_isolation(settings_file, mcp_file, prompt_file),
            "--permission-prompts", "none", ask_prompt(text, ctx)]


def prepare_session(sid: str) -> tuple[Path, Path, Path]:
    """Write the session's settings, MCP config and system prompt; return their paths."""
    sdir = paths.session_dir(sid)
    sdir.mkdir(parents=True, exist_ok=True)
    registry = load_registry(paths.registry_dirs())
    base = json.loads((SHARE / "settings.json").read_text())
    settings_file, mcp_file = sdir / "settings.json", sdir / "mcp.json"
    settings_file.write_text(json.dumps(build_settings(base, paths.rules_file(), registry), indent=2))
    mcp_file.write_text(json.dumps(mcp_config(registry), indent=2))
    return settings_file, mcp_file, system_prompt_file(sid)


def save_meta(sid: str, **fields) -> None:
    f = paths.session_dir(sid) / "meta.json"
    try:
        meta = json.loads(f.read_text())
    except (OSError, ValueError):
        meta = {"sid": sid, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    meta.update(fields)
    f.write_text(json.dumps(meta, indent=2))


def load_meta(sid: str) -> dict:
    try:
        return json.loads((paths.session_dir(sid) / "meta.json").read_text())
    except (OSError, ValueError):
        return {"sid": sid}


def signal_bar() -> None:
    subprocess.run(["pkill", "-RTMIN+10", "waybar"], capture_output=True)


def _result(cp: subprocess.CompletedProcess) -> str:
    try:
        return json.loads(cp.stdout).get("result") or "(no answer)"
    except ValueError:
        return (cp.stderr or cp.stdout or "the agent did not answer").strip()[-500:]


def cmd_ask() -> int:
    sid = str(uuid.uuid4())
    sdir = paths.session_dir(sid)
    sdir.mkdir(parents=True, exist_ok=True)
    asked = prompt(capture(sdir))
    if asked is None:
        return 0
    text, ctx = asked
    settings_file, mcp_file, prompt_file = prepare_session(sid)
    cwd = str(ctx.cwd or Path(os.environ.get("HOME", "/")))
    save_meta(sid, cwd=cwd, mode="ask", question=text)
    pidfile = paths.runtime_dir() / "ask.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()))
    signal_bar()
    try:
        cp = subprocess.run(ask_argv(sid, text, ctx, settings_file, mcp_file, prompt_file),
                            cwd=cwd, env=agent_env(sid), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    finally:
        pidfile.unlink(missing_ok=True)
        signal_bar()
    answer = _result(cp)
    (sdir / "answer.md").write_text(answer)
    short = answer if len(answer) <= 300 else answer[:300] + "…"
    pick = ui.choose("Agent", short, [("fix", "Fix it"), ("chat", "Open chat"), ("dismiss", "Dismiss")])
    if pick == "fix":
        return dispatch(["fix", sid])
    if pick == "chat":
        return dispatch(["chat", sid])
    return 0


COMMANDS = {"ask": lambda args: cmd_ask()}


def dispatch(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print("usage: hypr-agent " + " | ".join(sorted(COMMANDS)), file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


def main(argv: list[str]) -> int:
    return dispatch(argv)
