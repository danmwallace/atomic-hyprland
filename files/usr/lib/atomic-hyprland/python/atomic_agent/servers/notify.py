"""notify: post a desktop notification (asks first, like any change)."""
import subprocess

from ..ui import notify_body

_URGENCY = ("low", "normal", "critical")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def notify(summary: str, body: str = "", urgency: str = "normal") -> str:
    """Show a notification. urgency: low, normal or critical."""
    if urgency not in _URGENCY:
        return f"refused: urgency must be one of {', '.join(_URGENCY)}"
    cp = _run(["notify-send", "-a", "hypr-agent", "-u", urgency, summary, notify_body(body)])
    return "sent" if cp.returncode == 0 else f"exit {cp.returncode}\n{cp.stderr}"


def main() -> None:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    app = FastMCP("notify", log_level="WARNING")
    app.tool(annotations=ToolAnnotations(readOnlyHint=False))(notify)
    app.run()
