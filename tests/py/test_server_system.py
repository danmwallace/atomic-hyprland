import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from atomic_agent.registry import load_registry
from atomic_agent.servers import system
from helpers import tmpdir

HELPER = "/usr/libexec/atomic-hyprland/agent-root"
REPO = Path(__file__).resolve().parents[2]


class SystemServerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def fake(argv, input=None):
            self.calls.append((argv, input))
            return subprocess.CompletedProcess(argv, 0, "out\n", "")
        p = mock.patch.object(system, "_run", fake)
        p.start(); self.addCleanup(p.stop)
        self.root = tmpdir(self)
        e = mock.patch.dict(os.environ, {"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state"),
                                         "HYPR_AGENT_SESSION": "s1"}, clear=True)
        e.start(); self.addCleanup(e.stop)

    def argv(self):
        return self.calls[-1][0]

    def test_journal_argv(self):
        system.journal(unit="waybar.service", user=True, since="-10min", priority="err", lines=50)
        self.assertEqual(self.argv(), ["journalctl", "--no-pager", "-o", "short-iso", "--user", "-u", "waybar.service",
                                       "--since", "-10min", "-p", "err", "-n", "50"])
        system.journal()
        self.assertEqual(self.argv(), ["journalctl", "--no-pager", "-o", "short-iso", "--since", "-1h", "-n", "200"])

    def test_journal_caps_lines(self):
        system.journal(lines=99999)
        self.assertEqual(self.argv()[-2:], ["-n", "2000"])

    def test_journal_rejects_option_injection(self):
        self.assertIn("refused", system.journal(unit="--rotate"))
        self.assertIn("refused", system.journal(priority="--vacuum-size=1"))
        self.assertEqual(self.calls, [])

    def test_unit_status_and_failed(self):
        system.unit_status("tailscaled.service")
        self.assertEqual(self.argv(), ["systemctl", "--no-pager", "status", "tailscaled.service"])
        system.failed_units(user=True)
        self.assertEqual(self.argv(), ["systemctl", "--user", "--no-pager", "list-units", "--failed"])

    def test_user_restart_uses_systemctl_user(self):
        system.restart_unit("waybar.service", user=True)
        self.assertEqual(self.argv(), ["systemctl", "--user", "restart", "waybar.service"])

    def test_system_restart_uses_pkexec_helper(self):
        system.restart_unit("tailscaled.service")
        self.assertEqual(self.argv(), ["pkexec", HELPER, "unit", "restart", "tailscaled.service"])
        system.stop_unit("cups.service")
        self.assertEqual(self.argv(), ["pkexec", HELPER, "unit", "stop", "cups.service"])

    def test_bad_unit_refused_before_running(self):
        self.assertIn("refused", system.start_unit("-x.service", user=True))
        self.assertEqual(self.calls, [])

    def test_write_etc_passes_content_on_stdin(self):
        system.write_etc_file("/etc/app.conf", "key = 1\n")
        argv, stdin = self.calls[-1]
        sdir = self.root / "state/atomic-hyprland/agent/s1"
        self.assertEqual(argv, ["pkexec", HELPER, "etc-write", str(sdir), "/etc/app.conf"])
        self.assertEqual(stdin, "key = 1\n")
        self.assertTrue(sdir.is_dir())

    def test_bootc(self):
        system.bootc_upgrade()
        self.assertEqual(self.argv(), ["pkexec", HELPER, "bootc-upgrade"])
        system.bootc_rollback()
        self.assertEqual(self.argv(), ["pkexec", HELPER, "bootc-rollback"])

    def test_bootc_status_unprivileged(self):
        system.bootc_status()
        self.assertEqual(self.argv(), ["rpm-ostree", "status", "--json"])

    def test_list_units_argv(self):
        system.list_units(user=True, pattern="way*", state="failed")
        self.assertEqual(self.argv(), ["systemctl", "--user", "--no-pager", "list-units", "--all",
                                       "--state=failed", "--", "way*"])
        system.list_units()
        self.assertEqual(self.argv(), ["systemctl", "--no-pager", "list-units", "--all"])

    def test_list_unit_files_and_timers(self):
        system.list_unit_files(user=True, pattern="nonexist*")
        self.assertEqual(self.argv(), ["systemctl", "--user", "--no-pager", "list-unit-files", "--", "nonexist*"])
        system.list_timers()
        self.assertEqual(self.argv(), ["systemctl", "--no-pager", "list-timers", "--all"])

    def test_unit_file_shows_unit_and_dropins(self):
        system.unit_file("waybar.service", user=True)
        self.assertEqual(self.argv(), ["systemctl", "--user", "--no-pager", "cat", "waybar.service"])

    def test_listing_refuses_options_and_shell(self):
        for bad in ("--now", "-a", "x;rm", "$(id)", "a b", "x>y"):
            self.assertIn("refused", system.list_units(pattern=bad), bad)
            self.assertIn("refused", system.list_unit_files(pattern=bad), bad)
        self.assertIn("refused", system.list_units(state="--failed"))
        self.assertIn("refused", system.unit_file("--force"))
        self.assertEqual(self.calls, [])

    def test_inspect_runs_only_its_fixed_commands(self):
        system.inspect("disks")
        self.assertEqual([c[0][0] for c in self.calls], ["lsblk", "df", "findmnt"])
        self.assertIn("refused", system.inspect("rm -rf /"))
        self.assertEqual(set(system.INSPECT), {"disks", "network", "memory", "processes", "hardware",
                                               "battery", "flatpaks"})

    def test_inspect_labels_each_command(self):
        out = system.inspect("memory")
        self.assertIn("$ free -h\nout", out)
        self.assertIn("$ swapon --show\nout", out)

    def test_inspect_survives_a_missing_command(self):
        def missing(argv, input=None):
            raise FileNotFoundError(argv[0])
        with mock.patch.object(system, "_run", missing):
            self.assertIn("lspci: not installed", system.inspect("hardware"))

    def test_processes_keeps_the_top(self):
        many = "".join(f"{i} p\n" for i in range(200))
        with mock.patch.object(system, "_run", lambda argv, input=None: subprocess.CompletedProcess(argv, 0, many, "")):
            self.assertEqual(system.inspect("processes").count("\n"), 32)  # the "$ ps" label, the ps header and 30 processes

    def test_package(self):
        system.package("glow")
        self.assertEqual(self.argv(), ["rpm", "-q", "--", "glow"])
        for bad in ("-a", "--eval=%(id)", "a b", ""):
            self.assertIn("refused", system.package(bad), bad)

    def test_registry_file(self):
        reg = load_registry([REPO / "files/usr/share/atomic-hyprland/mcp.d"])
        d = reg["system"]
        self.assertEqual(d.spec, {"command": "/usr/libexec/atomic-hyprland/mcp-server", "args": ["system"]})
        self.assertEqual(sorted(d.read_only_tools), sorted(system.READ_TOOLS))
        self.assertEqual(sorted(d.root_tools), sorted(system.CHANGE_TOOLS))
        self.assertEqual(set(d.tool_notes), set(system.CHANGE_TOOLS))


if __name__ == "__main__":
    unittest.main()
