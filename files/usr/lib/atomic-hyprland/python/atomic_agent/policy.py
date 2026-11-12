"""What an approval card says, and which "always allow" rule it may offer.

Tool names are Claude Code's: built-ins (Bash, Edit, Write, ...) and MCP tools
as mcp__<server>__<tool>. root_tools and tool_notes are keyed by full names.
"""
import difflib
import json
import os
import re
import shlex
from dataclasses import dataclass

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
    title: str          # what will happen, from the action itself
    detail: str         # the literal command, diff or arguments
    undo: str
    rule: str | None    # the "always allow" rule offered, if any
    note: str = ""      # the model's own description, shown as its words


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
    return f"Edit(/{real})"


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


def card_for(tool_name: str, tool_input: dict, tool_notes: dict[str, str], root_tools: set[str]) -> Card:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    note = ""
    if tool_name == "Bash":
        detail = tool_input.get("command", "")
        first = detail.strip().splitlines()[0] if detail.strip() else ""
        title = f"Run: {first[:80]}{'…' if len(first) > 80 or len(detail.strip().splitlines()) > 1 else ''}"
        note = tool_input.get("description", "")
    elif tool_name == "Edit":
        title = f"Edit {path}"
        detail = _diff(path, tool_input.get("old_string", ""), tool_input.get("new_string", ""))
    elif tool_name == "MultiEdit":
        title = f"Edit {path}"
        detail = "\n".join(_diff(path, e.get("old_string", ""), e.get("new_string", ""))
                           for e in tool_input.get("edits", []))
    elif tool_name == "Write":
        title = f"{'Overwrite' if os.path.exists(path) else 'Create'} {path}"
        detail = "".join(tool_input.get("content", "").splitlines(keepends=True)[:40])
    elif tool_name.startswith("mcp__"):
        _, server, tool = tool_name.split("__", 2)
        title = f"{server}: {tool.replace('_', ' ')}"
        detail = json.dumps(tool_input, indent=2, sort_keys=True)
    else:
        title = tool_name
        detail = json.dumps(tool_input, indent=2, sort_keys=True)
    return Card(title=title, detail=detail, undo=undo_note(tool_name, tool_input, tool_notes),
                rule=always_rule(tool_name, tool_input, root_tools), note=note)
