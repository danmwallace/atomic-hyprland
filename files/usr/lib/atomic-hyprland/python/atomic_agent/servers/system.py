"""system: journal, unit status and bootc for agents; changes go through approvals.

Reads run as the user. System-scope changes run through the polkit-gated root
helper (pkexec agent-root); user units through systemctl --user.
"""
import os
import re
import subprocess

from .. import paths

HELPER = "/usr/libexec/atomic-hyprland/agent-root"
READ_TOOLS = ("journal", "unit_status", "failed_units", "bootc_status", "list_units", "list_unit_files",
              "unit_file", "list_timers", "inspect", "package")
CHANGE_TOOLS = ("restart_unit", "start_unit", "stop_unit", "bootc_upgrade", "bootc_rollback", "write_etc_file")
MAX_LINES = 2000
_UNIT = re.compile(r"[A-Za-z0-9@][A-Za-z0-9@._:\-]*\.(service|timer|socket|path|target|mount|scope|slice)")
_PRIORITY = re.compile(r"[0-7]|emerg|alert|crit|err|warning|notice|info|debug")
_SINCE = re.compile(r"[A-Za-z0-9 :.+\-]+")
_PATTERN = re.compile(r"[A-Za-z0-9@._:*?\[\]][A-Za-z0-9@._:*?\[\]\-]*")
_STATE = re.compile(r"[a-z]+(-[a-z]+)*")
_PACKAGE = re.compile(r"[A-Za-z0-9_.+][A-Za-z0-9_.+\-]*")
PROCESS_ROWS = 30
# inspect(topic): fixed, read-only commands; the agent picks a topic, never a command line.
INSPECT = {
    "disks": [["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS"],
              ["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "efivarfs"], ["findmnt", "--real"]],
    "network": [["ip", "-brief", "address"], ["ip", "route"],
                ["nmcli", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], ["resolvectl", "--no-pager", "status"]],
    "memory": [["free", "-h"], ["swapon", "--show"]],
    "processes": [["ps", "-eo", "pid,user,%cpu,%mem,etime,comm", "--sort=-%cpu"]],
    "hardware": [["lspci", "-k"], ["lsusb"]],
    "battery": [["upower", "--dump"]],
    "flatpaks": [["flatpak", "list", "--app", "--columns=application,version,origin"]],
}


class Refused(ValueError):
    pass


def _run(argv: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, input=input, capture_output=True, text=True, timeout=600)


def _text(cp: subprocess.CompletedProcess) -> str:
    out = (cp.stdout or "") + (cp.stderr or "")
    return out if cp.returncode == 0 else f"exit {cp.returncode}\n{out}"


def _unit(unit: str) -> str:
    if not _UNIT.fullmatch(unit or ""):
        raise Refused(f"refused: not a unit name: {unit!r}")
    return unit


def _guard(fn):
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Refused as exc:
            return str(exc)
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    wrapped.__wrapped__ = fn
    return wrapped


@_guard
def journal(unit: str | None = None, user: bool = False, since: str = "-1h",
            priority: str | None = None, lines: int = 200) -> str:
    """Read the journal (newest last). unit: one unit; user: the user journal; priority: e.g. err."""
    argv = ["journalctl", "--no-pager", "-o", "short-iso"]
    if user:
        argv.append("--user")
    if unit:
        argv += ["-u", _unit(unit)]
    if not _SINCE.fullmatch(since or "") or since.startswith("--"):
        raise Refused(f"refused: bad since: {since!r}")
    argv += ["--since", since]
    if priority:
        if not _PRIORITY.fullmatch(priority):
            raise Refused(f"refused: bad priority: {priority!r}")
        argv += ["-p", priority]
    argv += ["-n", str(max(1, min(int(lines), MAX_LINES)))]
    return _text(_run(argv))


@_guard
def unit_status(unit: str, user: bool = False) -> str:
    """systemctl status of one unit."""
    return _text(_run(["systemctl", *(["--user"] if user else []), "--no-pager", "status", _unit(unit)]))


@_guard
def failed_units(user: bool = False) -> str:
    """Units in the failed state."""
    return _text(_run(["systemctl", *(["--user"] if user else []), "--no-pager", "list-units", "--failed"]))


def _scope(user: bool) -> list[str]:
    return ["systemctl", *(["--user"] if user else []), "--no-pager"]


def _pattern(pattern: str | None) -> list[str]:
    if pattern is None:
        return []
    if not _PATTERN.fullmatch(pattern):
        raise Refused(f"refused: not a unit pattern: {pattern!r}")
    return ["--", pattern]


@_guard
def list_units(user: bool = False, pattern: str | None = None, state: str | None = None) -> str:
    """Units systemd knows about, loaded or not. pattern: a glob such as 'way*'; state: e.g. failed, running."""
    argv = [*_scope(user), "list-units", "--all"]
    if state is not None:
        if not _STATE.fullmatch(state):
            raise Refused(f"refused: not a unit state: {state!r}")
        argv.append(f"--state={state}")
    return _text(_run(argv + _pattern(pattern)))


@_guard
def list_unit_files(user: bool = False, pattern: str | None = None) -> str:
    """Installed unit files and whether they are enabled. pattern: a glob such as 'nonexist*'."""
    return _text(_run([*_scope(user), "list-unit-files", *_pattern(pattern)]))


@_guard
def unit_file(unit: str, user: bool = False) -> str:
    """A unit's file and drop-ins (systemctl cat)."""
    return _text(_run([*_scope(user), "cat", _unit(unit)]))


def list_timers(user: bool = False) -> str:
    """Timers, with their last and next run."""
    return _text(_run([*_scope(user), "list-timers", "--all"]))


@_guard
def inspect(topic: str) -> str:
    """Read-only system facts. topic: disks, network, memory, processes (top CPU), hardware,
    battery, flatpaks."""
    if topic not in INSPECT:
        raise Refused(f"refused: unknown topic {topic!r}; one of {', '.join(INSPECT)}")
    parts = []
    for argv in INSPECT[topic]:
        try:
            out = _text(_run(argv))
        except FileNotFoundError:
            out = f"{argv[0]}: not installed\n"
        if topic == "processes":
            out = "".join(out.splitlines(keepends=True)[:PROCESS_ROWS + 1])
        parts.append(f"$ {' '.join(argv)}\n{out}")
    return "\n".join(parts)


@_guard
def package(name: str) -> str:
    """The installed version of one RPM package (rpm -q)."""
    if not _PACKAGE.fullmatch(name or ""):
        raise Refused(f"refused: not a package name: {name!r}")
    return _text(_run(["rpm", "-q", "--", name]))


def bootc_status() -> str:
    """The booted, staged and rollback images (rpm-ostree status --json)."""
    return _text(_run(["rpm-ostree", "status", "--json"]))


def _unit_op(op: str, unit: str, user: bool) -> str:
    unit = _unit(unit)
    if user:
        return _text(_run(["systemctl", "--user", op, unit]))
    return _text(_run(["pkexec", HELPER, "unit", op, unit]))


@_guard
def restart_unit(unit: str, user: bool = False) -> str:
    """Restart a unit (system units ask for the admin password)."""
    return _unit_op("restart", unit, user)


@_guard
def start_unit(unit: str, user: bool = False) -> str:
    """Start a unit."""
    return _unit_op("start", unit, user)


@_guard
def stop_unit(unit: str, user: bool = False) -> str:
    """Stop a unit."""
    return _unit_op("stop", unit, user)


def bootc_upgrade() -> str:
    """Stage the newest image (applies at the next reboot)."""
    return _text(_run(["pkexec", HELPER, "bootc-upgrade"]))


def bootc_rollback() -> str:
    """Boot the previous image at the next reboot."""
    return _text(_run(["pkexec", HELPER, "bootc-rollback"]))


def write_etc_file(path: str, content: str) -> str:
    """Write a file under /etc (saved first, so undo can restore it)."""
    sdir = paths.session_dir(os.environ.get("HYPR_AGENT_SESSION") or "manual")
    sdir.mkdir(parents=True, exist_ok=True)
    return _text(_run(["pkexec", HELPER, "etc-write", str(sdir), path], input=content))


def main() -> None:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    app = FastMCP("system", log_level="WARNING")
    for fn in (journal, unit_status, failed_units, bootc_status, list_units, list_unit_files,
               unit_file, list_timers, inspect, package):
        app.tool(annotations=ToolAnnotations(readOnlyHint=True))(getattr(fn, "__wrapped__", fn))
    for fn in (restart_unit, start_unit, stop_unit, bootc_upgrade, bootc_rollback, write_etc_file):
        app.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))(getattr(fn, "__wrapped__", fn))
    app.run()
