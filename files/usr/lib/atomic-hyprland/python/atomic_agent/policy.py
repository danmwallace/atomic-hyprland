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
CANT_UNDO = "Can't be undone automatically."
FILE_UNDO = "Undo restores the file."

# A rule for a compound command would cover whatever follows the first part.
_COMPOUND = re.compile(r";|&&|\|\||\||>|<|`|\$\(|\n")
_SEGMENTS = re.compile(r"\s*(?:;|&&|\|\||\||\n)\s*")
_WRAPPERS = {"env", "command", "exec", "nohup", "time", "nice", "stdbuf"}
_NEVER_FIRST = {"sudo", "pkexec", "su", "run0", "doas", "bootc", "rm", "rmdir", "shred", "unlink"}


@dataclass
class Card:
    title: str
    detail: str
    undo: str
    rule: str | None


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


def _bash_never(command: str) -> bool:
    for segment in _SEGMENTS.split(command):
        w = _words(segment)
        if not w:
            continue
        if w[0] in _NEVER_FIRST:
            return True
        if w[0] == "git" and "push" in w[1:3]:
            return True
        if w[:3] == ["gh", "pr", "create"]:
            return True
        if w[0] == "find" and "-delete" in w:
            return True
    return False


def never_always(tool_name: str, tool_input: dict, root_tools: set[str]) -> bool:
    if tool_name in root_tools or tool_name.startswith("mcp__screen__"):
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
        if not command or _COMPOUND.search(command):
            return None
        return f"Bash({command}:*)"
    if tool_name in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        # Claude Code: //path is absolute; an Edit rule covers every file-editing tool.
        return f"Edit(/{path})" if path and path.startswith("/") else None
    return None


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
    if tool_name == "Bash":
        title = tool_input.get("description") or "Run a command"
        detail = tool_input.get("command", "")
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
                rule=always_rule(tool_name, tool_input, root_tools))
