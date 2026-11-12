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
