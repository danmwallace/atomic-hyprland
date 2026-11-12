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
        self.units_file = self.root / "agent-units"
        u = mock.patch.object(self.m, "UNITS_FILE", str(self.units_file))
        u.start(); self.addCleanup(u.stop)
        self.etc_file = self.root / "agent-etc"
        f = mock.patch.object(self.m, "ETC_FILE", str(self.etc_file))
        f.start(); self.addCleanup(f.stop)
        o = mock.patch.object(self.m, "UNITS_FILE_OWNER", os.getuid())
        o.start(); self.addCleanup(o.stop)
        self.aliases = {}
        self.env = {"PKEXEC_UID": str(os.getuid())}
        self.calls = []

    def run_main(self, *argv, stdin=""):
        def run(cmd, **kw):
            if cmd[:3] == ["systemctl", "show", "-p"]:
                return subprocess.CompletedProcess(cmd, 0, self.aliases.get(cmd[-1], cmd[-1]) + "\n", "")
            self.calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch("sys.stderr", io.StringIO()):
            return self.m.main(list(argv), self.env, run=run, stdin=io.StringIO(stdin))

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
        self.assertEqual(self.run_main("unit", "mask", "cups.service"), 2)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.run_main("unit", "restart", "cups.service"), 0)
        self.assertEqual(self.calls, [["systemctl", "restart", "cups.service"]])
        self.assertEqual(self.run_main("unit", "restart", "some-random.service"), 2)

    def test_upgrade_never_applies(self):
        self.assertEqual(self.run_main("bootc-upgrade"), 0)
        self.assertEqual(self.calls, [["bootc", "upgrade"]])
        self.assertEqual(self.run_main("bootc-upgrade", "--apply"), 2)

    def test_etc_write_snapshots_first(self):
        target = self.etc / "hosts"
        target.write_text("old\n")
        self.assertEqual(self.run_main("etc-write", str(self.sdir), str(target), stdin="new\n"), 0)
        self.assertEqual(target.read_text(), "new\n")
        lines = [json.loads(l) for l in (self.sdir / "manifest.jsonl").read_text().splitlines()]
        self.assertEqual(lines[0], {"path": str(target), "existed": True, "copy": "files/0"})
        self.assertEqual(lines[1], {"event": "applied", "path": str(target)})
        self.assertEqual((self.sdir / "files/0").read_text(), "old\n")
        # second write: no second snapshot (one more applied marker at most)
        self.run_main("etc-write", str(self.sdir), str(target), stdin="newer\n")
        lines = [json.loads(l) for l in (self.sdir / "manifest.jsonl").read_text().splitlines()]
        self.assertEqual(sum(1 for e in lines if "existed" in e), 1)

    def test_etc_write_new_file_records_absent(self):
        target = self.etc / "hosts"
        self.run_main("etc-write", str(self.sdir), str(target), stdin="x")
        entry = json.loads((self.sdir / "manifest.jsonl").read_text().splitlines()[0])
        self.assertEqual(entry, {"path": str(target), "existed": False, "copy": None})

    def test_snapshot_refuses_symlinked_files_dir(self):
        # C1: as root, a symlinked files/ (or manifest) would chown or overwrite /etc.
        victim = self.root / "victim"
        victim.mkdir()
        (self.sdir / "files").symlink_to(victim)
        self.assertNotEqual(self.run_main("etc-snapshot", str(self.sdir), str(self.etc / "hosts")), 0)
        self.assertEqual(list(victim.iterdir()), [])

    def test_snapshot_refuses_symlinked_manifest(self):
        victim = self.root / "victim.txt"
        victim.write_text("keep")
        (self.sdir / "manifest.jsonl").symlink_to(victim)
        self.assertNotEqual(self.run_main("etc-snapshot", str(self.sdir), str(self.etc / "hosts")), 0)
        self.assertEqual(victim.read_text(), "keep")

    def test_user_side_writes_drop_privileges(self):
        calls = []
        with mock.patch("os.setresuid", side_effect=lambda *a: calls.append(("uid",) + a)), \
             mock.patch("os.setresgid", side_effect=lambda *a: calls.append(("gid",) + a)), \
             mock.patch("os.fork", return_value=0), mock.patch("os._exit", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.m.as_user(os.getuid(), os.getgid(), lambda: None)
        self.assertIn(("uid", os.getuid(), os.getuid(), os.getuid()), calls)
        self.assertIn(("gid", os.getgid(), os.getgid(), os.getgid()), calls)

    def test_write_keeps_label_owner_and_mode(self):
        target = self.etc / "hosts"
        target.write_text("old")
        target.chmod(0o640)
        seen = {}
        real_get = os.getxattr
        def get(path, name, *a, **k):
            if name == "security.selinux":
                return b"system_u:object_r:net_conf_t:s0"
            return real_get(path, name, *a, **k)
        with mock.patch("os.getxattr", side_effect=get), \
             mock.patch("os.setxattr", side_effect=lambda p, n, v, *a, **k: seen.update({n: v})), \
             mock.patch("os.chown", side_effect=lambda p, u, g, *a, **k: seen.update(owner=(u, g))):
            self.m.write_file(str(target), b"new")
        self.assertEqual(target.read_text(), "new")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(seen["security.selinux"], b"system_u:object_r:net_conf_t:s0")
        self.assertEqual(seen["owner"], (os.getuid(), os.getgid()))

    def test_etc_restore(self):
        target = self.etc / "hosts"
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

    def test_refuses_private_files(self):
        secret = self.etc / "hosts"
        secret.write_text("hash")
        secret.chmod(0o600)
        self.assertEqual(self.run_main("etc-snapshot", str(self.sdir), str(secret)), 2)
        self.assertFalse((self.sdir / "files").exists())

    def test_refuses_protected_paths(self):
        for rel in ("shadow", "gshadow", "sudoers", "sudoers.d/x", "polkit-1/rules.d/x.rules", "pam.d/sudo",
                    "ssh/sshd_config", "containers/policy.json", "passwd", "security/limits.conf"):
            target = self.etc / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            self.assertEqual(self.run_main("etc-write", str(self.sdir), str(target), stdin="x"), 2, rel)
            self.assertFalse(target.exists(), rel)

    def test_restore_copy_symlink_refused(self):
        (self.sdir / "files").mkdir()
        (self.sdir / "files/0").symlink_to(self.etc / "elsewhere")
        (self.etc / "elsewhere").write_text("root data")
        self.assertEqual(self.run_main("etc-restore", str(self.etc / "a"), str(self.sdir / "files/0")), 2)
        self.assertFalse((self.etc / "a").exists())

    def test_units_limited(self):
        for unit in ("poweroff.target", "home.mount", "systemd-logind.service", "debug-shell.service",
                     "emergency.service", "rescue.service", "dbus-broker.service", "polkit.service",
                     "getty@tty1.service", "serial-getty@ttyS0.service"):
            self.assertEqual(self.run_main("unit", "stop", unit), 2, unit)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.run_main("unit", "restart", "tailscaled.service"), 0)
        self.assertEqual(self.run_main("unit", "start", "bootc-fetch-apply-updates.timer"), 0)

    def test_units_file_extends_allowlist(self):
        self.assertEqual(self.run_main("unit", "restart", "ollama.service"), 2)
        self.units_file.write_text("# extra units\nollama.service\n")
        self.units_file.chmod(0o666)
        self.assertEqual(self.run_main("unit", "restart", "ollama.service"), 2)  # writable by others: ignored
        self.units_file.chmod(0o644)
        self.assertEqual(self.run_main("unit", "restart", "ollama.service"), 0)

    def test_unit_alias_resolved(self):
        # an allowed name that is an alias of something else is judged by what it resolves to
        self.aliases["cups.service"] = "systemd-logind.service"
        self.assertEqual(self.run_main("unit", "stop", "cups.service"), 2)
        self.assertEqual(self.calls, [])

    def test_etc_allowlist(self):
        for rel in ("systemd/system/x.service", "ld.so.preload", "profile.d/x.sh", "cron.d/x",
                    "environment", "modprobe.d/x.conf", "udev/rules.d/x.rules", "atomic-hyprland/mcp.d/x.json",
                    "containers/systemd/x.container", "xdg/autostart/x.desktop"):
            target = self.etc / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            self.assertEqual(self.run_main("etc-write", str(self.sdir), str(target), stdin="x"), 2, rel)
            self.assertFalse(target.exists(), rel)
        for rel in ("tuned/profile/tuned.conf", "fwupd/fwupd.conf", "NetworkManager/conf.d/x.conf",
                    "atomic-hyprland/agent.conf", "atomic-hyprland/agent-units", "atomic-hyprland/agent-etc"):
            target = self.etc / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            self.assertEqual(self.run_main("etc-write", str(self.sdir), str(target), stdin="x"), 2, rel)
        self.assertEqual(self.run_main("etc-write", str(self.sdir), str(self.etc / "hosts"), stdin="x\n"), 0)

    def test_etc_file_extends_allowlist(self):
        (self.etc / "chrony.conf").write_text("pool x\n")
        self.assertEqual(self.run_main("etc-write", str(self.sdir), str(self.etc / "chrony.conf"), stdin="y"), 2)
        self.etc_file.write_text("# machine additions\nchrony.conf\n")
        self.assertEqual(self.run_main("etc-write", str(self.sdir), str(self.etc / "chrony.conf"), stdin="y"), 0)
        self.etc_file.write_text("atomic-hyprland/agent-etc\n")  # never self-extending
        target = self.etc / "atomic-hyprland/agent-etc"
        self.assertEqual(self.run_main("etc-write", str(self.sdir), str(target), stdin="sudoers\n"), 2)

    def test_unknown_op_refused(self):
        self.assertEqual(self.run_main("bootc-switch", "quay.io/evil"), 2)
        self.assertEqual(self.run_main(), 2)


if __name__ == "__main__":
    unittest.main()
