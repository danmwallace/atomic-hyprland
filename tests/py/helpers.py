"""Shared test helpers: temp dirs and stub executables on PATH."""
import os
import stat
import tempfile
from pathlib import Path


def tmpdir(test) -> Path:
    d = tempfile.TemporaryDirectory()
    test.addCleanup(d.cleanup)
    return Path(d.name)


def stub(bindir: Path, name: str, body: str) -> Path:
    """Write an executable bash stub. $ARGV_LOG, if set, collects one argv per line."""
    bindir.mkdir(parents=True, exist_ok=True)
    p = bindir / name
    p.write_text("#!/usr/bin/bash\n"
                 '[ -n "${ARGV_LOG:-}" ] && printf "%s\\n" "' + name + ' $*" >> "$ARGV_LOG"\n'
                 + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def write_json(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
