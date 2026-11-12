"""screen: capture a window, an output or a region (always asks first).

Screenshots can show anything on screen (mail, chats), so capture is never
read-only and never "always allow". Files land in the session's folder.
"""
import json
import os
import re
import subprocess
import time

from .. import paths

_REGION = re.compile(r"-?\d+,-?\d+ \d+x\d+")
_OUTPUT = re.compile(r"[A-Za-z0-9\-_.]+")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def _geometry(w: dict) -> str:
    (x, y), (wd, ht) = w["at"], w["size"]
    return f"{x},{y} {wd}x{ht}"


def _window_geometry(address: str | None) -> str:
    if address is None:
        return _geometry(json.loads(_run(["hyprctl", "-j", "activewindow"]).stdout))
    if not _ADDRESS.fullmatch(address):
        raise ValueError(f"not a window address: {address!r}")
    for w in json.loads(_run(["hyprctl", "-j", "clients"]).stdout):
        if w.get("address") == address:
            return _geometry(w)
    raise ValueError(f"no window {address}")


def capture(target: str = "window", address: str | None = None, output: str | None = None,
            region: str | None = None) -> str:
    """Screenshot a window (default: the focused one), an output, or a region "x,y wxh"; returns the PNG path."""
    try:
        if target == "window":
            where = ["-g", _window_geometry(address)]
        elif target == "output" and output and _OUTPUT.fullmatch(output):
            where = ["-o", output]
        elif target == "region" and region and _REGION.fullmatch(region):
            where = ["-g", region]
        else:
            raise ValueError(f"bad target {target!r}")
    except (ValueError, KeyError) as exc:
        return f"refused: {exc}"
    d = paths.session_dir(os.environ.get("HYPR_AGENT_SESSION") or "manual") / "screens"
    d.mkdir(parents=True, exist_ok=True)
    path = str(d / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000:06d}.png")
    cp = _run(["grim", *where, path])
    return path if cp.returncode == 0 else f"exit {cp.returncode}\n{cp.stderr}"


def main() -> None:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    app = FastMCP("screen", log_level="WARNING")
    app.tool(annotations=ToolAnnotations(readOnlyHint=False))(capture)
    app.run()
