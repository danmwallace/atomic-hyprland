"""What Super+A attaches: the focused window's screenshot, the clipboard, and
the working folder of the focused terminal. The prompt shows each as a chip
the user can remove before anything is sent.
"""
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

SHELLS = {"bash", "zsh", "fish", "elvish", "nu", "sh", "dash"}
TERMINAL_CLASSES = {"com.mitchellh.ghostty", "ghostty", "Alacritty", "alacritty", "kitty", "foot"}
DEFAULT_QUESTION = "What's wrong here? Explain the problem on screen and how to fix it."
ASK_LINE = "Ask: what's wrong here?   (or type a question)"
PASSWORD_HINT = "x-kde-passwordManagerHint"


@dataclass
class Context:
    screenshot: Path | None
    clipboard: str | None
    cwd: Path | None


def window_geometry(active: dict) -> str:
    (x, y), (w, h) = active["at"], active["size"]
    return f"{x},{y} {w}x{h}"


def _children(proc: Path) -> dict[int, list[int]]:
    tree: dict[int, list[int]] = {}
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            stat = (d / "stat").read_text()
        except OSError:
            continue
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        tree.setdefault(ppid, []).append(int(d.name))
    return tree


def terminal_cwd(pid: int, proc: Path = Path("/proc")) -> Path | None:
    """The working folder of the deepest shell under a terminal's process."""
    if not (proc / str(pid)).is_dir():
        return None
    tree = _children(proc)
    best: tuple[int, int] | None = None  # (depth, pid)
    stack = [(pid, 0)]
    while stack:
        p, depth = stack.pop()
        try:
            comm = (proc / str(p) / "comm").read_text().strip()
        except OSError:
            comm = ""
        if comm in SHELLS and (best is None or depth > best[0]):
            best = (depth, p)
        stack += [(c, depth + 1) for c in tree.get(p, [])]
    if best is None:
        return None
    try:
        return (proc / str(best[1]) / "cwd").resolve(strict=True)
    except OSError:
        return None


def clipboard_text(run=subprocess.run, limit: int = 4000) -> str | None:
    """Clipboard text, or None when empty or offered by a password manager."""
    types = run(["wl-paste", "--list-types"], capture_output=True, text=True, timeout=5)
    if types.returncode != 0 or PASSWORD_HINT in types.stdout.split():
        return None
    out = run(["wl-paste", "--no-newline", "--type", "text/plain"], capture_output=True, text=True, timeout=5)
    text = out.stdout if out.returncode == 0 else ""
    return text[:limit] if text.strip() else None


def capture(shot_dir: Path, run=subprocess.run) -> Context:
    """shot_dir holds the screenshot until the user decides to keep it (not the agent's folder)."""
    active = {}
    try:
        active = json.loads(run(["hyprctl", "-j", "activewindow"], capture_output=True, text=True, timeout=5).stdout)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        pass
    shot = None
    if active.get("at") and active.get("size"):
        shot_dir.mkdir(parents=True, exist_ok=True)
        path = shot_dir / "ask.png"
        if run(["grim", "-g", window_geometry(active), str(path)], capture_output=True, timeout=10).returncode == 0:
            shot = path
    cwd = terminal_cwd(int(active["pid"])) if active.get("class") in TERMINAL_CLASSES and active.get("pid") else None
    return Context(screenshot=shot, clipboard=clipboard_text(run=run), cwd=cwd)


def chip_lines(ctx: Context) -> list[str]:
    lines = [ASK_LINE]
    if ctx.screenshot:
        lines.append("󰹑  window screenshot   (select to remove)")
    if ctx.clipboard:
        first = " ".join(ctx.clipboard.split())[:40]
        lines.append(f"󰅍  clipboard: {first}   (select to remove)")
    if ctx.cwd:
        lines.append(f"󰉋  {ctx.cwd}   (select to remove)")
    return lines


def _wofi(prompt: str, lines: list[str]) -> str | None:
    out = subprocess.run(["wofi", "--dmenu", "-D", "allow_markup=false", "--prompt", prompt,
                          "--lines", str(len(lines) + 1)],
                         input="\n".join(lines) + "\n", capture_output=True, text=True)
    return out.stdout.rstrip("\n") if out.returncode == 0 else None


def prompt(ctx: Context, menu=_wofi) -> tuple[str, Context] | None:
    while True:
        lines = chip_lines(ctx)
        pick = menu("Ask the agent", lines)
        if pick is None:
            return None
        if pick == ASK_LINE or not pick.strip():
            return DEFAULT_QUESTION, ctx
        if pick in lines[1:]:
            if pick.startswith("󰹑"):
                ctx = replace(ctx, screenshot=None)
            elif pick.startswith("󰅍"):
                ctx = replace(ctx, clipboard=None)
            else:
                ctx = replace(ctx, cwd=None)
            continue
        return pick.strip(), ctx
