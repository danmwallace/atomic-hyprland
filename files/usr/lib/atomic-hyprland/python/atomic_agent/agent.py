"""hypr-agent: Super+A asks a read-only agent about the screen; Fix it lets it
work in the background behind approval cards. See the design in
docs/superpowers/specs/2026-11-11-agentic-desktop-design.md.

Every session runs Claude Code headless from its own session folder with no
setting sources (--setting-sources "": neither ~/.claude/settings.json nor a
repo's .claude/settings.json can add hooks or allow rules), only its own
settings file, its own MCP servers (--strict-mcp-config) and a snapshot hook for
undo. The user's terminal folder is passed with --add-dir.
"""
import json
import os
import shutil
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
POST_HOOK = "hypr-agent hook post-tool-use"
EDIT_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
# Claude Code waits this long for an MCP tool; an approval waits up to 10 minutes.
MCP_TOOL_TIMEOUT_MS = "660000"


def _user_rules(rules_path: Path) -> list[str]:
    """The saved "always allow" rules; only strings (anything else would make Claude
    Code drop the whole settings file, hooks and denies included)."""
    try:
        allow = json.loads(rules_path.read_text()).get("permissions", {}).get("allow", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [r for r in allow if isinstance(r, str) and r.strip()] if isinstance(allow, list) else []


def build_settings(base: dict, rules_path: Path, registry: dict[str, ServerDef], include_rules: bool = True) -> dict:
    """include_rules=False for ask mode, which stays read-only whatever was always-allowed."""
    settings = json.loads(json.dumps(base))
    perms = settings.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    for d in registry.values():
        allow += [f"mcp__{d.name}__{t}" for t in d.read_only_tools]
    if include_rules:
        allow += _user_rules(rules_path)
    perms["allow"] = list(dict.fromkeys(allow))
    perms["defaultMode"] = "default"
    settings["hooks"] = {
        "PreToolUse": [{"matcher": EDIT_MATCHER, "hooks": [{"type": "command", "command": HOOK}]}],
        "PostToolUse": [{"matcher": EDIT_MATCHER, "hooks": [{"type": "command", "command": POST_HOOK}]}],
    }
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


def _isolation(settings_file: Path, mcp_file: Path, prompt_file: Path, work_dir: str | None = None) -> list[str]:
    argv = ["--setting-sources", "", "--settings", str(settings_file),
            "--mcp-config", str(mcp_file), "--strict-mcp-config",
            "--append-system-prompt-file", str(prompt_file)]
    if work_dir:
        argv += ["--add-dir", work_dir]
    return argv


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
            *_isolation(settings_file, mcp_file, prompt_file, str(ctx.cwd) if ctx.cwd else None),
            "--permission-prompts", "none", ask_prompt(text, ctx)]


FIX_PROMPT = ("Fix the problem now. Say what you will change before each step; every change shows "
              "the user an approval card. Prefer Edit/Write for files. When done, summarise what you "
              "changed and how to check it.")


def fix_argv(sid: str, settings_file: Path, mcp_file: Path, prompt_file: Path, work_dir: str | None = None) -> list[str]:
    return ["claude", "-p", "--resume", sid, "--output-format", "json",
            *_isolation(settings_file, mcp_file, prompt_file, work_dir),
            "--permission-prompt-tool", "mcp__approvals__prompt", FIX_PROMPT]


def chat_argv(sid: str, settings_file: Path, mcp_file: Path, prompt_file: Path, work_dir: str | None = None) -> list[str]:
    # Interactive: Claude Code's own terminal prompts answer permissions (the
    # permission-prompt tool is --print only); settings and the undo hook are the same.
    return ["claude", "--resume", sid, *_isolation(settings_file, mcp_file, prompt_file, work_dir)]


def prepare_session(sid: str, mode: str = "fix") -> tuple[Path, Path, Path]:
    """Write the session's settings, MCP config and system prompt; return their paths.
    mode "ask" leaves out the user's "always allow" rules."""
    sdir = paths.session_dir(sid)
    sdir.mkdir(parents=True, exist_ok=True)
    registry = load_registry(paths.registry_dirs())
    base = json.loads((SHARE / "settings.json").read_text())
    settings_file, mcp_file = sdir / "settings.json", sdir / "mcp.json"
    settings = build_settings(base, paths.rules_file(), registry, include_rules=(mode != "ask"))
    settings_file.write_text(json.dumps(settings, indent=2))
    mcp_file.write_text(json.dumps(mcp_config(registry), indent=2))
    return settings_file, mcp_file, system_prompt_file(sid)


def save_meta(sid: str, **fields) -> None:
    f = paths.session_dir(sid) / "meta.json"
    f.parent.mkdir(parents=True, exist_ok=True)
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


def finalize_screenshot(ctx: Context, shot: Path, sdir: Path) -> Context:
    """Keep the screenshot only if its chip survived the prompt; otherwise delete it,
    so it is never readable in the agent's folder."""
    from dataclasses import replace
    if ctx.screenshot is None:
        shot.unlink(missing_ok=True)
        return ctx
    (sdir / "screens").mkdir(parents=True, exist_ok=True)
    kept = sdir / "screens" / shot.name
    # shutil.move, not os.replace: the runtime dir is tmpfs and the state dir is not (EXDEV).
    shutil.move(shot, kept)
    return replace(ctx, screenshot=kept)


def answer_card(answer: str) -> tuple[str, list[tuple[str, str]], dict[str, str]]:
    """The answer card: plain text up front, the whole answer one click away."""
    body = ui.plain_summary(answer) + "\n\nClick for: full answer · Fix it · chat"
    choices = [("read", "Read the full answer"), ("fix", "Fix it"), ("chat", "Open chat"), ("dismiss", "Dismiss")]
    return body, choices, {"read": answer}


def cmd_ask() -> int:
    sid = str(uuid.uuid4())
    sdir = paths.session_dir(sid)
    shot_dir = paths.runtime_dir() / f"ask-{sid}"
    captured = capture(shot_dir)
    asked = prompt(captured)
    if asked is None:
        if captured.screenshot:
            captured.screenshot.unlink(missing_ok=True)
        shutil.rmtree(shot_dir, ignore_errors=True)
        return 0
    text, ctx = asked
    sdir.mkdir(parents=True, exist_ok=True)
    if captured.screenshot:
        ctx = finalize_screenshot(ctx, captured.screenshot, sdir)
    shutil.rmtree(shot_dir, ignore_errors=True)
    settings_file, mcp_file, prompt_file = prepare_session(sid, mode="ask")
    cwd = str(ctx.cwd) if ctx.cwd else None
    save_meta(sid, cwd=cwd, mode="ask", question=text)
    pidfile = paths.runtime_dir() / "ask.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(os.getpid()))
    signal_bar()
    try:
        # Run from the session folder, never from the user's (possibly untrusted) project.
        cp = subprocess.run(ask_argv(sid, text, ctx, settings_file, mcp_file, prompt_file),
                            cwd=sdir, env=agent_env(sid), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    finally:
        pidfile.unlink(missing_ok=True)
        signal_bar()
    answer = _result(cp)
    (sdir / "answer.md").write_text(answer)
    body, choices, views = answer_card(answer)
    pick = ui.choose("Agent", body, choices, views=views)
    if pick == "fix":
        return dispatch(["fix", sid])
    if pick == "chat":
        return dispatch(["chat", sid])
    return 0


HELPER = "/usr/libexec/atomic-hyprland/agent-root"


def start_fix(sid: str, run=subprocess.run) -> str:
    unit = f"hypr-agent-{sid[:8]}"
    run(["systemd-run", "--user", f"--unit={unit}", "--collect", "-p", "Type=exec",
         "--", "hypr-agent", "run-fix", sid], capture_output=True, text=True)
    signal_bar()
    return unit


def _changes(sid: str) -> list[str]:
    from .snapshots import changed
    try:
        return changed(paths.session_dir(sid))
    except (OSError, ValueError):
        return []


def run_fix(sid: str) -> int:
    settings_file, mcp_file, prompt_file = prepare_session(sid)
    meta = load_meta(sid)
    save_meta(sid, mode="fix")
    sdir = paths.session_dir(sid)
    cp = subprocess.run(fix_argv(sid, settings_file, mcp_file, prompt_file, meta.get("cwd")),
                        cwd=sdir, env=agent_env(sid), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    result = _result(cp)
    (sdir / "result.md").write_text(result)
    save_meta(sid, mode="done")
    signal_bar()
    changed = _changes(sid)
    body = ui.plain_summary(result, limit=300)
    if changed:
        body += "\n\nChanged (undo restores them):\n" + "\n".join(changed[:8])
    choices = ([("undo", "Undo the changes")] if changed else []) + [
        ("read", "Read the full result"), ("chat", "Open chat"), ("dismiss", "Dismiss")]
    pick = ui.choose("Agent: done", body, choices, views={"read": result})
    if pick == "undo":
        return dispatch(["undo", sid])
    if pick == "chat":
        return dispatch(["chat", sid])
    return 0


def open_chat(sid: str, run=subprocess.run) -> int:
    settings_file, mcp_file, prompt_file = prepare_session(sid)
    argv = chat_argv(sid, settings_file, mcp_file, prompt_file, load_meta(sid).get("cwd"))
    # The terminal starts in the session folder; the user's folder is an --add-dir.
    env_prefix = ["env", "-C", str(paths.session_dir(sid)), "-u", "CLAUDECODE",
                  f"HYPR_AGENT_SESSION={sid}", f"MCP_TOOL_TIMEOUT={MCP_TOOL_TIMEOUT_MS}"]
    return run(["uwsm-app", "--", "hypr-terminal", "-e", *env_prefix, *argv]).returncode


def stop_all(run=subprocess.run, settle: float = 0.6) -> None:
    # Deny first, so a waiting approvals server answers Claude and cleans up its own
    # card; then stop the units; then clear whatever a killed server left behind.
    for pid_ in ui.list_pending():
        ui.answer(pid_, "deny")
    if ui.list_pending():
        time.sleep(settle)
    run(["systemctl", "--user", "stop", "hypr-agent-*.service"], capture_output=True)
    pidfile = paths.runtime_dir() / "ask.pid"
    try:
        pid = int(pidfile.read_text())
    except (OSError, ValueError):
        pid = None
    if pid:
        run(["pkill", "-TERM", "-P", str(pid)], capture_output=True)
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        pidfile.unlink(missing_ok=True)
    for pid_ in ui.list_pending():
        data = ui.read_pending(pid_) or {}
        for ext in ("answer", "json"):
            (paths.pending_dir() / f"{pid_}.{ext}").unlink(missing_ok=True)
        if data.get("notification"):
            run(["makoctl", "dismiss", "-n", str(data["notification"])], capture_output=True)
    for stray in paths.pending_dir().glob("*.answer") if paths.pending_dir().is_dir() else []:
        stray.unlink(missing_ok=True)
    signal_bar()


def _helper_restore(run):
    def restore(path: str, copy: str | None) -> None:
        cp = run(["pkexec", HELPER, "etc-restore", path, copy or "-"], capture_output=True, text=True)
        if cp.returncode != 0:
            raise OSError(f"agent-root etc-restore {path}: exit {cp.returncode}")
    return restore


def undo_session(sid: str, run=subprocess.run) -> list[str]:
    from .snapshots import undo
    return undo(paths.session_dir(sid), restore_etc=_helper_restore(run))


def cmd_undo(sid: str) -> int:
    try:
        restored = undo_session(sid)
    except OSError as exc:
        subprocess.run(["notify-send", "-a", "hypr-agent", "-u", "critical", "Agent: undo failed", str(exc)])
        return 1
    msg = "\n".join(restored) if restored else "Nothing to undo."
    subprocess.run(["notify-send", "-a", "hypr-agent", "Agent: undone", msg])
    return 0


def cmd_review() -> int:
    pid = ui.oldest_pending()
    if pid is None:
        subprocess.run(["notify-send", "-a", "hypr-agent", "Agent", "No approvals waiting."])
        return 0
    ui.review(pid)
    return 0


def cmd_hook(args: list[str]) -> int:
    from .snapshots import hook_post_tool_use, hook_pre_tool_use
    if args not in (["pre-tool-use"], ["post-tool-use"]):
        return 2
    try:
        event = json.load(sys.stdin)
    except ValueError as exc:
        print(f"hypr-agent: unreadable hook input ({exc}); blocking", file=sys.stderr)
        return 2 if args == ["pre-tool-use"] else 0
    return hook_pre_tool_use(event) if args == ["pre-tool-use"] else hook_post_tool_use(event)


def cmd_sessions() -> int:
    d = paths.state_dir()
    for sdir in sorted(d.iterdir() if d.is_dir() else [], key=lambda p: p.stat().st_mtime):
        meta = load_meta(sdir.name)
        n = len(_changes(sdir.name))
        print(f"{sdir.name}\t{meta.get('mode', '?')}\t{meta.get('created', '?')}\t{n} change{'s' if n != 1 else ''}")
    return 0


def cmd_pr_target() -> int:
    from .prtarget import can_push, target_repo
    repo = target_repo()
    if repo and can_push(repo):
        print(repo)
        return 0
    where = repo or "the image's repository"
    print(f"PRs are off: your GitHub login can't push to {where}. "
          "Fork it and set repo= in /etc/atomic-hyprland/agent.conf", file=sys.stderr)
    return 3


def _one(args: list[str], fn) -> int:
    if len(args) != 1:
        print("needs a session id (see: hypr-agent sessions)", file=sys.stderr)
        return 2
    return fn(args[0])


COMMANDS = {
    "ask": lambda args: cmd_ask(),
    "fix": lambda args: _one(args, lambda sid: (start_fix(sid), 0)[1]),
    "run-fix": lambda args: _one(args, run_fix),
    "chat": lambda args: _one(args, open_chat),
    "stop": lambda args: (stop_all(), 0)[1],
    "undo": lambda args: _one(args, cmd_undo),
    "review": lambda args: cmd_review(),
    "hook": cmd_hook,
    "sessions": lambda args: cmd_sessions(),
    "pr-target": lambda args: cmd_pr_target(),
}


def dispatch(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print("usage: hypr-agent " + " | ".join(sorted(COMMANDS)), file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


def main(argv: list[str]) -> int:
    if argv[:1] == ["hook"]:
        return dispatch(argv)  # hooks fail closed with their own exit codes
    try:
        return dispatch(argv)
    except Exception as e:
        # Run from a keybind there is no terminal: say so on screen, keep the traceback for the journal.
        import traceback
        traceback.print_exc()
        cmd = argv[0] if argv else ""
        subprocess.run(["notify-send", "-a", "hypr-agent", "-u", "critical",
                        f"hypr-agent {cmd} failed", f"{type(e).__name__}: {e}"], capture_output=True)
        return 1
