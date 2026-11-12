"""The permission-prompt tool for hypr-agent sessions (claude --permission-prompt-tool).

Claude Code calls prompt(tool_name, input, tool_use_id) for every action its
rules do not already allow. The answer comes from an approval card; "always"
also saves the card's rule in ~/.config/atomic-hyprland/agent/permissions.json.
"""
import json
import os

from .. import paths, ui
from ..policy import card_for
from ..registry import load_registry

DENIED = {"behavior": "deny", "message": "Denied by the user"}


def _registry_maps() -> tuple[dict[str, str], set[str]]:
    notes: dict[str, str] = {}
    roots: set[str] = set()
    for d in load_registry(paths.registry_dirs()).values():
        notes.update({f"mcp__{d.name}__{t}": n for t, n in d.tool_notes.items()})
        roots.update(f"mcp__{d.name}__{t}" for t in d.root_tools)
    return notes, roots


def _ask(card, session: str) -> str:
    pid = ui.new_pending(card, session)
    ui.show_card(pid)
    return ui.wait_answer(pid)  # closes the card once answered


def save_rule(rule: str) -> None:
    f = paths.rules_file()
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        data = {}
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    if rule not in allow:
        allow.append(rule)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(f)


SKIPPED = {"behavior": "deny",
           "message": "The user skipped the question. Decide yourself, and say what you chose and why."}


def _question_result(tool_input: dict, choice: str) -> dict:
    # A question card answers {"answers": {question: label}}; Claude Code reads them
    # from updatedInput (as the Agent SDK's canUseTool does). Anything else: skipped.
    try:
        answers = json.loads(choice)["answers"]
    except (ValueError, TypeError, KeyError):
        return dict(SKIPPED)
    if not isinstance(answers, dict) or not answers:
        return dict(SKIPPED)
    return {"behavior": "allow", "updatedInput": {**tool_input, "answers": answers}}


def decide(tool_name: str, tool_input: dict, ask=_ask) -> dict:
    notes, roots = _registry_maps()
    card = card_for(tool_name, tool_input, notes, roots)
    choice = ask(card, os.environ.get("HYPR_AGENT_SESSION", ""))
    if tool_name == "AskUserQuestion":
        return _question_result(tool_input, choice)
    if choice == "always" and card.rule:
        save_rule(card.rule)
    if choice in ("allow", "always"):
        return {"behavior": "allow", "updatedInput": tool_input}
    return dict(DENIED)


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("approvals", log_level="WARNING")

    # Text only: Claude Code rejects a permission answer that comes back as structured
    # content ("Permission prompt tool returned an invalid result"), which FastMCP adds
    # by default for a str return.
    @app.tool(structured_output=False)
    def prompt(tool_name: str, input: dict, tool_use_id: str | None = None) -> str:
        """Ask the user to approve a tool call; returns Claude Code's permission JSON."""
        return json.dumps(decide(tool_name, input))

    app.run()
