"""hyprland: see and (with approval) arrange the desktop through Hyprland's own dispatchers.

No synthetic keyboard or mouse input: windows are focused, moved, resized,
closed and launched with hl.dsp Lua dispatchers (hyprctl dispatch '<lua>').
"""
import re
import subprocess

READ_TOOLS = ("list_windows", "list_workspaces", "list_monitors", "active_window", "list_binds")
CHANGE_TOOLS = ("focus_window", "move_window_to_workspace", "resize_window", "close_window",
                "switch_workspace", "launch", "reload_config")
_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
_WORKSPACE = re.compile(r"[A-Za-z0-9:_+\-]{1,64}")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def _text(cp: subprocess.CompletedProcess) -> str:
    out = (cp.stdout or "") + (cp.stderr or "")
    return out if cp.returncode == 0 else f"exit {cp.returncode}\n{out}"


def lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


def _window(address: str) -> str:
    if not _ADDRESS.fullmatch(str(address)):
        raise ValueError(f"not a window address: {address!r}")
    return lua_str(f"address:{address}")


def _workspace(ws) -> str:
    if isinstance(ws, int) or (isinstance(ws, str) and ws.isdigit()):
        return str(int(ws))
    if not _WORKSPACE.fullmatch(str(ws)):
        raise ValueError(f"not a workspace: {ws!r}")
    return lua_str(ws)


def _size(n) -> int:
    n = int(n)
    if not 1 <= n <= 16384:
        raise ValueError(f"not a size: {n!r}")
    return n


def dispatch_expr(tool: str, **a) -> str:
    if tool == "focus_window":
        return f"hl.dsp.focus({{ window = {_window(a['address'])} }})"
    if tool == "move_window_to_workspace":
        return (f"hl.dsp.window.move({{ workspace = {_workspace(a['workspace'])}, "
                f"window = {_window(a['address'])}, follow = false }})")
    if tool == "resize_window":
        return (f"hl.dsp.window.resize({{ x = {_size(a['width'])}, y = {_size(a['height'])}, "
                f"window = {_window(a['address'])} }})")
    if tool == "close_window":
        return f"hl.dsp.window.close({{ window = {_window(a['address'])} }})"
    if tool == "switch_workspace":
        return f"hl.dsp.focus({{ workspace = {_workspace(a['workspace'])} }})"
    if tool == "launch":
        return f"hl.dsp.exec_cmd({lua_str('uwsm-app -- ' + a['command'])})"
    if tool == "reload_config":
        return "hl.dsp.reload_config()"
    raise ValueError(f"unknown tool: {tool}")


def _dispatch(tool: str, **a) -> str:
    try:
        expr = dispatch_expr(tool, **a)
    except ValueError as exc:
        return f"refused: {exc}"
    return _text(_run(["hyprctl", "dispatch", expr]))


def list_windows() -> str:
    """All windows (hyprctl clients) as JSON: address, class, title, workspace, at, size."""
    return _text(_run(["hyprctl", "-j", "clients"]))


def list_workspaces() -> str:
    """Workspaces as JSON."""
    return _text(_run(["hyprctl", "-j", "workspaces"]))


def list_monitors() -> str:
    """Monitors as JSON."""
    return _text(_run(["hyprctl", "-j", "monitors"]))


def active_window() -> str:
    """The focused window as JSON."""
    return _text(_run(["hyprctl", "-j", "activewindow"]))


def list_binds() -> str:
    """Key bindings as JSON."""
    return _text(_run(["hyprctl", "-j", "binds"]))


def focus_window(address: str) -> str:
    """Focus a window by address (from list_windows)."""
    return _dispatch("focus_window", address=address)


def move_window_to_workspace(address: str, workspace: str) -> str:
    """Move a window to a workspace (number or name) without following it."""
    return _dispatch("move_window_to_workspace", address=address, workspace=workspace)


def resize_window(address: str, width: int, height: int) -> str:
    """Resize a window to width x height pixels."""
    return _dispatch("resize_window", address=address, width=width, height=height)


def close_window(address: str) -> str:
    """Close a window (the app may ask to save first)."""
    return _dispatch("close_window", address=address)


def switch_workspace(workspace: str) -> str:
    """Switch to a workspace (number or name)."""
    return _dispatch("switch_workspace", workspace=workspace)


def launch(command: str) -> str:
    """Start an application (through uwsm-app, as the session launches apps)."""
    return _dispatch("launch", command=command)


def reload_config() -> str:
    """Reload Hyprland's config."""
    return _dispatch("reload_config")


def main() -> None:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    app = FastMCP("hyprland", log_level="WARNING")
    for name in READ_TOOLS:
        app.tool(annotations=ToolAnnotations(readOnlyHint=True))(globals()[name])
    for name in CHANGE_TOOLS:
        app.tool(annotations=ToolAnnotations(readOnlyHint=False))(globals()[name])
    app.run()
