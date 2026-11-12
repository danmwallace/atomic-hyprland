"""Cards: approval requests and the agent's answer/done cards.

mako draws no buttons, so a card is a notification whose default action
(a left click) opens a one-key wofi menu; Super+Y (`hypr-agent review`) opens
the menu for the oldest pending approval. A right click dismisses: Deny.

Pending approvals are files in $XDG_RUNTIME_DIR/hypr-agent/pending:
<id>.json holds the card, <id>.answer the choice (allow | deny | always).
Ids sort by creation time, so the oldest is the first in name order.
"""
import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from . import paths
from .policy import Card

ALLOW, DENY, DETAILS = "Allow", "Deny", "Details…"
ALWAYS = "Always allow: "


def _pending(pid: str, ext: str) -> Path:
    return paths.pending_dir() / f"{pid}.{ext}"


def new_pending(card: Card, session: str) -> str:
    d = paths.pending_dir()
    d.mkdir(parents=True, exist_ok=True)
    pid = "%013d-%s" % (time.time_ns() // 1_000_000, uuid.uuid4().hex[:6])
    _pending(pid, "json").write_text(json.dumps({**asdict(card), "session": session}))
    return pid


def read_pending(pid: str) -> dict | None:
    try:
        return json.loads(_pending(pid, "json").read_text())
    except (OSError, ValueError):
        return None


def answer(pid: str, choice: str) -> None:
    if choice not in ("allow", "deny", "always"):
        raise ValueError(choice)
    if _pending(pid, "json").exists():
        _pending(pid, "answer").write_text(choice)


def list_pending() -> list[str]:
    d = paths.pending_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def oldest_pending() -> str | None:
    pending = list_pending()
    return pending[0] if pending else None


def wait_answer(pid: str, timeout: float = 600.0, poll: float = 0.25) -> str:
    card, ans = _pending(pid, "json"), _pending(pid, "answer")
    deadline = time.monotonic() + timeout
    choice = "deny"
    while time.monotonic() < deadline:
        if ans.exists():
            choice = ans.read_text().strip() or "deny"
            break
        if not card.exists():
            break
        time.sleep(poll)
    for p in (ans, card):
        p.unlink(missing_ok=True)
    return choice


def _wofi(prompt: str, lines: list[str]) -> str | None:
    out = subprocess.run(["wofi", "--dmenu", "--prompt", prompt, "--lines", str(len(lines) + 1)],
                         input="\n".join(lines) + "\n", capture_output=True, text=True)
    pick = out.stdout.strip()
    return pick if out.returncode == 0 and pick else None


def _details(text: str) -> None:
    f = paths.runtime_dir() / "details.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    subprocess.run(["hypr-terminal", "-e", "less", str(f)])


def review(pid: str, menu=_wofi) -> None:
    card = read_pending(pid)
    if card is None:
        return
    lines = [ALLOW, DENY]
    if card.get("rule"):
        lines.append(ALWAYS + card["rule"])
    lines.append(DETAILS)
    while True:
        pick = menu(card["title"], lines)
        if pick is None:
            return
        if pick == DETAILS:
            _details(f"{card['title']}\n\n{card['detail']}\n\n{card['undo']}\n")
            continue
        choice = {ALLOW: "allow", DENY: "deny"}.get(pick, "always" if pick.startswith(ALWAYS) else None)
        if choice:
            answer(pid, choice)
        return


def _notify(title: str, body: str, urgency: str = "normal") -> subprocess.Popen:
    return subprocess.Popen(["notify-send", "-a", "hypr-agent", "-u", urgency, "-p", "-A", "default=Open",
                             "--wait", title, body], stdout=subprocess.PIPE, text=True)


def _await_action(proc: subprocess.Popen) -> tuple[str | None, str | None]:
    """notify-send -p --wait prints the notification id, then the chosen action (if any)."""
    out, _ = proc.communicate()
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return (lines[0] if lines else None), (lines[1] if len(lines) > 1 else None)


def card_body(card: dict) -> str:
    detail = card["detail"] if len(card["detail"]) <= 300 else card["detail"][:300] + "…"
    return f"{detail}\n\n{card['undo']}\nClick to answer (or Super+Y)."


def show_card(pid: str, notify=_notify) -> threading.Thread:
    """Show the approval card in the background; a click opens the menu, a dismissal denies."""
    card = read_pending(pid)

    def worker():
        proc = notify(card["title"], card_body(card), "critical")
        nid, action = _await_action(proc)
        if nid:
            data = read_pending(pid)
            if data is not None:
                data["notification"] = nid
                _pending(pid, "json").write_text(json.dumps(data))
        if action == "default":
            review(pid)
        else:
            answer(pid, "deny")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def close_card(nid: str | None) -> None:
    if nid:
        subprocess.run(["makoctl", "dismiss", "-n", str(nid)], capture_output=True)


def choose(title: str, body: str, choices: list[tuple[str, str]], menu=_wofi, notify=_notify) -> str | None:
    """A card with a menu of choices; returns the chosen key, or None if dismissed."""
    _, action = _await_action(notify(title, body))
    if action != "default":
        return None
    labels = {label: key for key, label in choices}
    pick = menu(title, [label for _, label in choices])
    return labels.get(pick) if pick else None
