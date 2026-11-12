"""Cards: approval requests and the agent's answer/done cards.

A card is a notification with buttons for its main choices; its default action
(a left click) opens a one-key wofi menu with all of them; Super+Y
(`hypr-agent review`) opens the menu for the oldest pending approval. Closing an approval card without answering it is Deny. A card that
merely times out stays answerable: swaync hides it into its panel without
closing it.

Pending approvals are files in $XDG_RUNTIME_DIR/hypr-agent/pending:
<id>.json holds the card, <id>.answer the choice (allow | deny | always), or for
a question card {"answers": {question: label}}.
Ids sort by creation time, so the oldest is the first in name order.
"""
import functools
import json
import os
import re
import shutil
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
SKIP = "Skip: let the agent decide"
MD_READER = "/usr/libexec/atomic-hyprland/md-reader"
EXPLAIN = "Allow lets the agent do this now. Deny blocks it, and the agent stops that step."


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


def answer_questions(pid: str, answers: dict[str, str]) -> None:
    if _pending(pid, "json").exists():
        _pending(pid, "answer").write_text(json.dumps({"answers": answers}))


def list_pending() -> list[str]:
    d = paths.pending_dir()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def oldest_pending() -> str | None:
    pending = list_pending()
    return pending[0] if pending else None


def _record_notification(pid: str, nid: str) -> None:
    """Store the card's notification id; never recreates a pending entry already gone."""
    data = read_pending(pid)
    if data is None:
        return
    data["notification"] = nid
    try:
        fd = os.open(_pending(pid, "json"), os.O_WRONLY | os.O_TRUNC)
    except FileNotFoundError:
        return
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data))


def discard_pending(pid: str) -> None:
    """Remove a pending entry and close its card (after it was answered, or on stop)."""
    data = read_pending(pid) or {}
    for ext in ("answer", "json"):
        _pending(pid, ext).unlink(missing_ok=True)
    close_card(data.get("notification"))


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
    discard_pending(pid)
    return choice


def _wofi(prompt: str, lines: list[str]) -> str | None:
    # No markup: a crafted title or rule must not be able to hide what it says.
    out = subprocess.run(["wofi", "--dmenu", "-D", "allow_markup=false", "--prompt", prompt,
                          "--lines", str(len(lines) + 1)],
                         input="\n".join(lines) + "\n", capture_output=True, text=True)
    pick = out.stdout.strip()
    return pick if out.returncode == 0 and pick else None


def plain_summary(md: str, limit: int = 400) -> str:
    """Markdown to the plain text a notification can show: no fences, emphasis or
    heading marks; code lines indented; cut at a word near the limit."""
    out, fence = [], False
    for line in md.strip().splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            out.append("  " + line)
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        out.append(line.replace("**", "").replace("__", "").replace("`", ""))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(None, 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip() + "…"


def details_text(card: dict) -> str:
    note = f"Agent's note: {card['note']}\n" if card.get("note") else ""
    head = card.get("title", "")
    if card.get("summary"):
        head += f"\n{card['summary']}"
    return f"{head}\n\n{EXPLAIN}\n\n{card.get('detail', '')}\n\n{note}{card.get('undo', '')}\n"


def _page(name: str, text: str, argv: list[str]) -> None:
    f = paths.runtime_dir() / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    subprocess.run(["hypr-terminal", "-e", *argv, str(f)])


def _details(text: str) -> None:
    # Plain less, never a markdown renderer: an approval's Details must show the exact
    # command or diff, and markdown would turn *, _ and # into formatting and drop <tags>.
    _page("details.txt", text, ["less"])


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def show_markdown(text: str) -> None:
    """The agent's full answer or result, rendered by glow; plain text if glow is missing.
    Model output can echo the screen or clipboard, so control characters (an OSC 52
    clipboard write, a title or screen escape) are removed first; md-reader pages glow
    through less -R (colours only) at the window's width."""
    text = _CONTROL.sub("", text)
    if shutil.which("glow"):
        _page("answer.md", text, [MD_READER])
    else:
        _page("answer.txt", plain_summary(text, limit=len(text) + 1), ["less"])


def _review_questions(pid: str, card: dict, menu) -> None:
    answers = {}
    for q in card["questions"]:
        lines = {_flat(f"{o.get('label', '')} — {o['description']}" if o.get("description") else o.get("label", "")):
                 o.get("label", "") for o in q.get("options", [])}
        pick = menu(_one(q.get("question", "") or card.get("summary", "")), [*lines, SKIP])
        if pick is None:
            return  # Escape: the card stays pending
        if pick == SKIP or pick not in lines:
            answer(pid, "deny")
            return
        answers[q.get("question", "")] = lines[pick]
    answer_questions(pid, answers)


def _flat(text: str) -> str:
    """One menu line: a newline in an option must not become a line of its own."""
    return " ".join("".join(c if c.isprintable() else " " for c in text).split())


def _one(text: str, width: int = 80) -> str:
    first = (text.strip().splitlines() or [""])[0]
    return first[:width] + ("…" if len(first) > width else "")


def review(pid: str, menu=_wofi) -> None:
    card = read_pending(pid)
    if card is None:
        return
    if card.get("questions"):
        _review_questions(pid, card, menu)
        return
    lines = [ALLOW, DENY]
    if card.get("rule"):
        lines.append(ALWAYS + card["rule"])
    lines.append(DETAILS)
    while True:
        pick = menu(card.get("summary") or card["title"], lines)
        if pick is None:
            return
        if pick == DETAILS:
            _details(details_text(card))
            continue
        choice = {ALLOW: "allow", DENY: "deny"}.get(pick, "always" if pick.startswith(ALWAYS) else None)
        if choice:
            answer(pid, choice)
        return


_BUS = ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
        "--object-path", "/org/freedesktop/Notifications", "--method"]


@functools.lru_cache(maxsize=1)
def server_renders_markup() -> bool:
    """Whether the notification server parses the body as markup (swaync always does).
    Unknown counts as yes: escaping on a plain-text server only looks odd, while not
    escaping on a markup server lets <span size="1"> hide part of a command."""
    try:
        cp = subprocess.run(_BUS + ["org.freedesktop.Notifications.GetCapabilities"],
                            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return True
    if cp.returncode != 0 or not cp.stdout.strip():
        return True
    return "'body-markup'" in cp.stdout


def notify_body(text: str) -> str:
    """The body as the server will show it literally."""
    if not server_renders_markup():
        return text
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def close_argv(nid: str) -> list[str]:
    return _BUS + ["org.freedesktop.Notifications.CloseNotification", str(nid)]


def _notify(title: str, body: str, urgency: str = "normal", timeout_ms: int | None = None,
            buttons: list[tuple[str, str]] = ()) -> subprocess.Popen:
    """A click on the card is the "default" action; buttons are extra actions (swaync draws them)."""
    argv = ["notify-send", "-a", "hypr-agent", "-u", urgency, "-p", "-A", "default=Open", "--wait"]
    for key, label in buttons:
        argv += ["-A", f"{key}={label}"]
    if timeout_ms is not None:
        argv += ["-t", str(timeout_ms)]
    return subprocess.Popen(argv + [title, notify_body(body)], stdout=subprocess.PIPE, text=True)


def _await_action(proc: subprocess.Popen, on_id=None) -> tuple[str | None, str | None]:
    """notify-send -p --wait prints the notification id at once, then the chosen action
    (if any) when the card is clicked or closed."""
    nid = (proc.stdout.readline() or "").strip() or None
    if nid and on_id:
        on_id(nid)
    rest, _ = proc.communicate()
    lines = [l.strip() for l in rest.splitlines() if l.strip()]
    return nid, (lines[0] if lines else None)


def card_body(card: dict) -> str:
    detail = card.get("preview") or (card["detail"] if len(card["detail"]) <= 300 else card["detail"][:300] + "…")
    note = f"Agent's note: {card['note']}\n" if card.get("note") else ""
    undo = f"{card['undo']}\n" if card.get("undo") else ""
    return f"{detail}\n\n{note}{undo}Click for details (or Super+Y)."


def show_card(pid: str, notify=_notify) -> threading.Thread:
    """Show the approval card in the background. Its Allow / Deny buttons answer it; a
    click opens the menu (Always allow, Details); closing it denies. A question card has
    no buttons: its options are in the menu."""
    card = read_pending(pid)
    buttons = [] if card.get("questions") else [("allow", ALLOW), ("deny", DENY)]

    def worker():
        proc = notify(card["title"], card_body(card), "critical", buttons=buttons)
        _, action = _await_action(proc, on_id=lambda nid: _record_notification(pid, nid))
        if action == "default":
            review(pid)
        elif action == "allow" and buttons:
            answer(pid, "allow")
        else:
            answer(pid, "deny")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def close_card(nid: str | None) -> None:
    if nid:
        subprocess.run(close_argv(nid), capture_output=True)


def choose(title: str, body: str, choices: list[tuple[str, str]], menu=_wofi, notify=_notify,
           views: dict[str, str] | None = None, pager=show_markdown) -> str | None:
    """A card with a menu of choices; returns the chosen key, or None if dismissed.
    Every choice but dismiss is also a button on the card. Clicking the card opens the
    menu; a key in views opens its text in the pager, then the menu comes back."""
    # No expiry: Fix it / Undo live on this card (swaync only hides it into its panel).
    buttons = [(k, label) for k, label in choices if k != "dismiss"]
    _, action = _await_action(notify(title, body, "normal", 0, buttons=buttons))
    keys = {k for k, _ in choices}
    if action != "default" and action not in keys:
        return None
    labels = {label: key for key, label in choices}
    views = views or {}
    first = action if action in keys else None
    while True:
        if first is not None:
            key, first = first, None
        else:
            pick = menu(title, [label for _, label in choices])
            key = labels.get(pick) if pick else None
        if key in views:
            pager(views[key])
            continue
        return key
