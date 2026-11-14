"""What an approval card says, and which "always allow" rule it may offer.

Tool names are Claude Code's: built-ins (Bash, Edit, Write, ...) and MCP tools
as mcp__<server>__<tool>. root_tools and tool_notes are keyed by full names.
"""
import difflib
import json
import os
import re
import shlex
from dataclasses import dataclass, field

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# Tools that can run anything: an "always allow" rule would cover every command.
NEVER_ALWAYS_TOOLS = {"mcp__hyprland__launch"}
CANT_UNDO = "Can't be undone automatically."
FILE_UNDO = "Undo restores the file."

# A rule for a compound command would cover whatever follows the first part.
_COMPOUND = re.compile(r";|&|\||>|<|`|\$\(|\n")
_SEGMENTS = re.compile(r"\s*(?:;|&&|\|\||\||&|\n)\s*")
_GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# "Always allow" for a file is an allowlist: only non-hidden files under $HOME.
# Dotfiles and dot-folders (shell startup, ~/.config, ~/.local, ~/.ssh, .git,
# .claude, the agent's own config) and anything outside home can run code or
# widen the agent's reach later, so they keep one-time cards.
_GLOB = re.compile(r"[*?\[\]{}]")
# Characters Claude Code's rule syntax would read as patterns or structure.
_RULE_UNSAFE = re.compile(r"[*?\[\]{}()]")
_WRAPPERS = {"env", "command", "exec", "nohup", "time", "nice", "stdbuf"}
_NEVER_FIRST = {"sudo", "pkexec", "su", "run0", "doas", "bootc", "rm", "rmdir", "shred", "unlink"}


@dataclass
class Card:
    title: str          # the kind of action, in words ("The agent wants to run a command")
    detail: str         # the literal command, diff or arguments
    undo: str
    rule: str | None    # the "always allow" rule offered, if any
    note: str = ""      # the model's own description, shown as its words
    summary: str = ""   # one line from the action itself: the command, path or first argument
    preview: str = ""   # the notification body: short, plain text
    questions: list = field(default_factory=list)  # AskUserQuestion: answered, not approved


def _words(segment: str) -> list[str]:
    try:
        words = shlex.split(segment)
    except ValueError:
        words = segment.split()
    while words and (words[0] in _WRAPPERS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0])
                     or (words[0].startswith("-") and words[0] != "-")):
        words.pop(0)
    if words:
        words[0] = os.path.basename(words[0])
    return words


def _git_subcommand(words: list[str]) -> str | None:
    i = 1
    while i < len(words):
        w = words[i]
        if w in _GIT_OPTS_WITH_ARG:
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return w
    return None


def _bash_never(command: str) -> bool:
    for segment in _SEGMENTS.split(command):
        w = _words(segment)
        if not w:
            continue
        if w[0] in _NEVER_FIRST:
            return True
        if w[0] == "git" and _git_subcommand(w) == "push":
            return True
        if w[:3] == ["gh", "pr", "create"]:
            return True
        if w[0] == "find" and "-delete" in w:
            return True
    return False


def never_always(tool_name: str, tool_input: dict, root_tools: set[str]) -> bool:
    if tool_name in root_tools or tool_name in NEVER_ALWAYS_TOOLS or tool_name.startswith("mcp__screen__"):
        return True
    if tool_name == "Bash":
        return _bash_never(tool_input.get("command", ""))
    if tool_name == "Write":
        path = tool_input.get("file_path", "")
        return not tool_input.get("content") and os.path.exists(path)
    return False


def always_rule(tool_name: str, tool_input: dict, root_tools: set[str] = frozenset()) -> str | None:
    if never_always(tool_name, tool_input, set(root_tools)):
        return None
    if tool_name.startswith("mcp__"):
        return tool_name
    if tool_name == "Bash":
        command = tool_input.get("command", "").strip()
        if not command or _COMPOUND.search(command) or _RULE_UNSAFE.search(command):
            return None
        # Exact match, not a prefix: Bash(cmd:*) would also allow cmd plus any
        # extra arguments (find ... -delete after approving find ...).
        return f"Bash({command})"
    if tool_name in EDIT_TOOLS:
        return _edit_rule(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    return None


def _edit_rule(path: str) -> str | None:
    if not path.startswith("/") or _GLOB.search(path) or "/../" in path + "/" or "/./" in path + "/":
        return None
    real = os.path.realpath(path)
    home = os.path.realpath(os.environ.get("HOME") or os.path.expanduser("~"))
    if not real.startswith(home + "/"):
        return None
    if any(part.startswith(".") for part in real[len(home) + 1:].split("/")):
        return None
    # Folders on PATH (and ~/bin) hold programs: a file there runs as a command.
    path_dirs = {os.path.realpath(d) for d in os.environ.get("PATH", "").split(":") if d}
    path_dirs.add(os.path.join(home, "bin"))
    if any(real.startswith(d + "/") for d in path_dirs):
        return None
    # Claude Code: //path is absolute; an Edit rule covers every file-editing tool.
    # The rule keeps the path as written (the one the user sees and the session uses);
    # rule_variants() adds the resolved form when the two differ.
    return f"Edit(/{path})"


def rule_variants(rule: str) -> list[str]:
    """Every form of a rule that has to be saved for it to take effect.

    Where a path runs through a symlink (on bootc /home links to /var/home, and
    ~/Notebook may link into ~/Syncthing), Claude Code allows an edit only when both
    the path as written and its resolved target are allowed: either rule alone is
    refused (tested with Claude Code 2.1.325, 2026-11-14).
    """
    if rule.startswith("Edit(//") and rule.endswith(")"):
        path = rule[len("Edit(/"):-1]
        real = os.path.realpath(path)
        if real != path:
            return [rule, f"Edit(/{real})"]
    return [rule]


def undo_note(tool_name: str, tool_input: dict, tool_notes: dict[str, str]) -> str:
    if tool_name in EDIT_TOOLS:
        return FILE_UNDO
    if tool_name.startswith("mcp__"):
        return tool_notes.get(tool_name, CANT_UNDO)
    return CANT_UNDO


def _diff(path: str, old: str, new: str) -> str:
    lines = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                 fromfile=path, tofile=path)
    return "".join(lines)


def _one_line(text: str, width: int = 80) -> str:
    lines = text.strip().splitlines()
    first = lines[0] if lines else ""
    return first[:width] + ("…" if len(first) > width or len(lines) > 1 else "")


def _clip(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


_PLAIN_KEY = re.compile(r"[A-Za-z0-9_.-]+")


def _kv(tool_input: dict) -> str:
    """Arguments as "key: value" lines, one line each: a value with a newline or other
    control character is shown escaped, so it cannot fake extra argument lines."""
    out = []
    for k in sorted(tool_input):
        v = tool_input[k]
        key = k if _PLAIN_KEY.fullmatch(k) else json.dumps(k)
        out.append(f"{key}: {v if isinstance(v, str) and v.isprintable() else json.dumps(v)}")
    return "\n".join(out)


def _changed_lines(diff: str) -> str:
    rows = diff.splitlines()
    plus = sum(1 for l in rows if l.startswith("+") and not l.startswith("+++"))
    minus = sum(1 for l in rows if l.startswith("-") and not l.startswith("---"))
    return f"+{plus} −{minus} lines"


def _question_text(questions: list) -> str:
    parts = []
    for q in questions:
        opts = "\n".join(f"  • {o.get('label', '')}" + (f": {o['description']}" if o.get("description") else "")
                         for o in q.get("options", []))
        parts.append(f"{q.get('question', '')}\n{opts}")
    return "\n\n".join(parts)


def card_for(tool_name: str, tool_input: dict, tool_notes: dict[str, str], root_tools: set[str]) -> Card:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    note, questions = "", []
    if tool_name == "Bash":
        detail = tool_input.get("command", "")
        title, summary, preview = "The agent wants to run a command", f"Run: {_one_line(detail)}", _clip(detail.strip())
        note = tool_input.get("description", "")
    elif tool_name in ("Edit", "MultiEdit"):
        edits = [tool_input] if tool_name == "Edit" else tool_input.get("edits", [])
        detail = "\n".join(_diff(path, e.get("old_string", ""), e.get("new_string", "")) for e in edits)
        title, summary, preview = "The agent wants to edit a file", f"Edit {path}", f"{path} ({_changed_lines(detail)})"
    elif tool_name == "Write":
        content = tool_input.get("content", "")
        detail = "".join(content.splitlines(keepends=True)[:40])
        verb = "overwrite" if os.path.exists(path) else "create"
        title, summary, preview = f"The agent wants to {verb} a file", f"{verb.capitalize()} {path}", f"{path} ({len(content.splitlines())} lines)"
    elif tool_name == "AskUserQuestion":
        questions = list(tool_input.get("questions", []))
        detail = _question_text(questions)
        first = questions[0] if questions else {}
        title, summary = "The agent has a question", _one_line(first.get("question", ""))
        labels = " · ".join(o.get("label", "") for o in first.get("options", []))
        preview = _clip(first.get("question", "")) + (f"\n\nOptions: {labels}" if labels else "")
    elif tool_name.startswith("mcp__"):
        _, server, tool = tool_name.split("__", 2)
        detail = _kv(tool_input)
        action = f"{server}: {tool.replace('_', ' ')}"
        # summary is the menu prompt: it names the tool, never just one of its arguments.
        title, summary, preview = f"The agent wants to use {action}", action, _clip(detail)
    else:
        detail = _kv(tool_input)
        title, summary, preview = f"The agent wants to use {tool_name}", tool_name, _clip(detail)
    undo = "" if questions else undo_note(tool_name, tool_input, tool_notes)
    return Card(title=title, detail=detail, undo=undo, rule=None if questions else always_rule(tool_name, tool_input, root_tools),
                note=note, summary=summary, preview=preview, questions=questions)
