"""Where self-improvement PRs go: the image's own repository, or a fork.

The image records its source repo at build time (/usr/share/atomic-hyprland/
image-source, from the Containerfile's IMAGE_SOURCE). A machine can point
elsewhere with `repo = owner/name` in /etc/atomic-hyprland/agent.conf. PRs are
offered only when the user's gh login can push there.
"""
import re
import subprocess
from pathlib import Path

_REPO = re.compile(r"(?:(?:https?://)?github\.com[/:]|git@github\.com:)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?")


def normalise(raw: str) -> str | None:
    m = _REPO.fullmatch(raw.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def target_repo(source_file: Path = Path("/usr/share/atomic-hyprland/image-source"),
                conf: Path = Path("/etc/atomic-hyprland/agent.conf")) -> str | None:
    try:
        for line in conf.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "repo" and value.strip():
                return normalise(value)
    except OSError:
        pass
    try:
        return normalise(source_file.read_text())
    except OSError:
        return None


def can_push(repo: str, run=subprocess.run) -> bool:
    cp = run(["gh", "api", f"repos/{repo}", "--jq", ".permissions.push"], capture_output=True, text=True)
    return cp.returncode == 0 and cp.stdout.strip() == "true"


def push_status(repo: str, run=subprocess.run) -> str:
    """ok, logged-out, no-push or error.

    The login is checked first: a home restored onto a new install can keep
    gh's hosts.yml while the token in the keyring is gone, and then every API
    call fails. Calling that "can't push" sends the user off to fork the repo.
    """
    auth = run(["gh", "auth", "status", "--hostname", "github.com"], capture_output=True, text=True)
    if auth.returncode != 0:
        return "logged-out"
    cp = run(["gh", "api", f"repos/{repo}", "--jq", ".permissions.push"], capture_output=True, text=True)
    if cp.returncode != 0:
        return "error"
    return "ok" if cp.stdout.strip() == "true" else "no-push"


def off_message(repo: str | None, status: str) -> str:
    """What `hypr-agent pr-target` prints when PRs are off."""
    if status == "logged-out":
        return ("PRs are off: gh isn't logged in to GitHub (gh auth status failed). "
                "Run gh auth login, then try again.")
    where = repo or "the image's repository"
    if status == "error":
        return f"PRs are off: couldn't check push access to {where} (gh api failed). Try again later."
    return (f"PRs are off: your GitHub login can't push to {where}. "
            "Fork it and set repo= in /etc/atomic-hyprland/agent.conf")
