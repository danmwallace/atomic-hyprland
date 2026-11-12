"""Where the agent keeps its state, config and runtime files (XDG-aware)."""
import os
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("HOME") or os.path.expanduser("~"))


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else _home() / fallback


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "atomic-hyprland" / "agent"


def session_dir(sid: str) -> Path:
    return state_dir() / sid


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "hypr-agent"


def pending_dir() -> Path:
    return runtime_dir() / "pending"


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "atomic-hyprland"


def rules_file() -> Path:
    return config_dir() / "agent" / "permissions.json"


def registry_dirs() -> list[Path]:
    # Later entries override same-named servers from earlier ones: image, machine, user.
    return [
        Path(os.environ.get("ATOMIC_AGENT_SHARE", "/usr/share/atomic-hyprland/mcp.d")),
        Path(os.environ.get("ATOMIC_AGENT_ETC", "/etc/atomic-hyprland/mcp.d")),
        config_dir() / "mcp.d",
    ]


def managed_file() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "atomic-hyprland" / "mcp-managed.json"
