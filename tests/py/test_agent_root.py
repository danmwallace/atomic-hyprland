import io
import json
import os
import subprocess
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

from helpers import tmpdir

HELPER = Path(__file__).resolve().parents[2] / "files/usr/libexec/atomic-hyprland/agent-root"


def load():
    return SourceFileLoader("agent_root", str(HELPER)).load_module()


class AgentRootTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.m = load()
        self.etc = self.root / "etc"
        self.etc.mkdir()
        self.home = self.root / "home"
        self.sdir = self.home / ".local/state/atomic-hyprland/agent/s1"
        self.sdir.mkdir(parents=True)
        p = mock.patch.object(self.m, "ETC", str(self.etc))
        p.start(); self.addCleanup(p.stop)
        q = mock.patch.object(self.m, "home_of", lambda uid: str(self.home))
        q.start(); self.addCleanup(q.stop)
        self.env = {"PKEXEC_UID": str(os.getuid())}
        self.calls = []

    def run_main(self, *argv, stdin=""):
        def run(cmd, **kw):
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        with mock.patch("sys.stderr", io.StringIO()):
            return self.m.main(list(argv), self.env, run=run, stdin=io.StringIO(stdin), chown=lambda *a: None)

    def test_rejects_traversal(self):
        self.assertEqual(self.run_main("etc-write", str(self.sdir), f"{self.etc}/../usr/bin/x", stdin="x"), 2)
        self.assertFalse((self.root / "usr/bin/x").exists())

    def test_rejects_symlink_escape(self):
        (self.root / "usr").mkdir()
        (self.etc / "link").symlink_to(self.root / "usr")
        self.assertEqual(self.run_main("etc-write", str(self.sdir), f"{self.etc}/link/evil", stdin="x"), 2)
        self.assertFalse((self.root / "usr/evil").exists())
        (self.etc / "file-link").symlink_to(self.root / "usr" / "target")
        self.assertEqual(self.run_main("etc-write", str(self.sdir), f"{self.etc}/file-link", stdin="x"), 2)

    def test_rejects_foreign_session_dir(self):
        other = self.root / "elsewhere"
        other.mkdir()
        self.assertEqual(self.run_main("etc-snapshot", str(other), f"{self.etc}/hosts"), 2)
        self.assertEqual(self.run_main("etc-snapshot", f"{self.home}/../elsewhere", f"{self.etc}/hosts"), 2)

    def test_rejects_bad_unit(self):
        self.assertEqual(self.run_main("unit", "restart", "foo;rm"), 2)
        self.assertEqual(self.run_main("unit", "mask", "sshd.service"), 2)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.run_main("unit", "restart", "sshd.service"), 0)
        self.assertEqual(self.calls, [["systemctl", "restart", "sshd.service"]])

    def test_upgrade_never_applies(self):
        self.assertEqual(self.run_main("bootc-upgrade"), 0)
        self.assertEqual(self.calls, [["bootc", "upgrade"]])
        self.assertEqual(self.run_main("bootc-upgrade", "--apply"), 2)

    def test_etc_write_snapshots_first(self):
        target = self.etc / "app.conf"
        target.write_text("old\n")
        self.assertEqual(self.run_main("etc-write", str(self.sdir), str(target), stdin="new\n"), 0)
        self.assertEqual(target.read_text(), "new\n")
        entry = json.loads((self.sdir / "manifest.jsonl").read_text().splitlines()[0])
        self.assertEqual(entry, {"path": str(target), "existed": True, "copy": "files/0"})
        self.assertEqual((self.sdir / "files/0").read_text(), "old\n")
        # second write: no second snapshot
        self.run_main("etc-write", str(self.sdir), str(target), stdin="newer\n")
        self.assertEqual(len((self.sdir / "manifest.jsonl").read_text().splitlines()), 1)

    def test_etc_write_new_file_records_absent(self):
        target = self.etc / "new.conf"
        self.run_main("etc-write", str(self.sdir), str(target), stdin="x")
        entry = json.loads((self.sdir / "manifest.jsonl").read_text().splitlines()[0])
        self.assertEqual(entry, {"path": str(target), "existed": False, "copy": None})

    def test_etc_restore(self):
        target = self.etc / "app.conf"
        target.write_text("changed")
        (self.sdir / "files").mkdir()
        (self.sdir / "files/0").write_text("orig")
        self.assertEqual(self.run_main("etc-restore", str(target), str(self.sdir / "files/0")), 0)
        self.assertEqual(target.read_text(), "orig")
        self.assertEqual(self.run_main("etc-restore", str(target), "-"), 0)
        self.assertFalse(target.exists())

    def test_etc_restore_copy_must_be_users(self):
        outside = self.root / "outside"
        outside.write_text("x")
        self.assertEqual(self.run_main("etc-restore", str(self.etc / "a"), str(outside)), 2)

    def test_unknown_op_refused(self):
        self.assertEqual(self.run_main("bootc-switch", "quay.io/evil"), 2)
        self.assertEqual(self.run_main(), 2)


if __name__ == "__main__":
    unittest.main()
