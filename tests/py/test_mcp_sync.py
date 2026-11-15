import contextlib
import io
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from atomic_agent import mcp_sync
from atomic_agent.registry import ServerDef
from atomic_agent.secrets import SecretError
from helpers import tmpdir, write_json


def stdio(name):
    return ServerDef(name=name, spec={"command": "/x/" + name, "args": ["a"]})


class Recorder:
    """A subprocess.run stand-in: `claude mcp get` succeeds for names in `exists`."""

    def __init__(self, exists=()):
        self.exists = set(exists)
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        rc = 0
        if argv[:3] == ["claude", "mcp", "get"]:
            rc = 0 if argv[3] in self.exists else 1
        return subprocess.CompletedProcess(argv, rc, "", "")

    def verbs(self):
        return [(c[2], c[-2] if c[2] == "add-json" else c[-1]) for c in self.calls if c[2] != "get"]


class ClaudeSyncTest(unittest.TestCase):
    def test_client_entry_wraps_stdio(self):
        self.assertEqual(mcp_sync.client_entry(stdio("hyprland")),
                         {"type": "stdio", "command": "hypr-mcp", "args": ["run", "hyprland"]})
        url = ServerDef(name="w", spec={"type": "http", "url": "https://x.test"})
        self.assertEqual(mcp_sync.client_entry(url), {"type": "http", "url": "https://x.test"})

    def test_adds_new_server(self):
        rec = Recorder()
        managed = mcp_sync.sync_claude({"hyprland": stdio("hyprland")}, set(), run=rec)
        add = [c for c in rec.calls if "add-json" in c][0]
        self.assertEqual(add[:6], ["claude", "mcp", "add-json", "--scope", "user", "hyprland"])
        self.assertEqual(json.loads(add[6])["args"], ["run", "hyprland"])
        self.assertEqual(managed, {"hyprland"})

    def test_updates_managed(self):
        rec = Recorder(exists={"hyprland"})
        mcp_sync.sync_claude({"hyprland": stdio("hyprland")}, {"hyprland"}, run=rec)
        self.assertEqual(rec.verbs(), [("remove", "hyprland"), ("add-json", "hyprland")])

    def test_skips_user_owned(self):
        rec = Recorder(exists={"hyprland"})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            managed = mcp_sync.sync_claude({"hyprland": stdio("hyprland")}, set(), run=rec)
        self.assertEqual(rec.verbs(), [])
        self.assertEqual(managed, set())
        self.assertIn("hyprland", err.getvalue())

    def test_removes_dropped(self):
        rec = Recorder(exists={"old"})
        managed = mcp_sync.sync_claude({}, {"old"}, run=rec)
        self.assertEqual(rec.verbs(), [("remove", "old")])
        self.assertEqual(managed, set())


class GeminiSyncTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.settings = self.root / ".gemini" / "settings.json"

    def test_gemini_preserves_other_keys(self):
        write_json(self.settings, json.dumps({"theme": "x", "mcpServers": {"mine": {"command": "m"}, "gone": {"command": "g"}}}))
        defs = {"hyprland": stdio("hyprland"),
                "web": ServerDef(name="web", spec={"type": "http", "url": "https://h.test"}),
                "ev": ServerDef(name="ev", spec={"type": "sse", "url": "https://s.test"})}
        managed = mcp_sync.sync_gemini(defs, {"gone"}, self.settings)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["theme"], "x")
        self.assertEqual(data["mcpServers"]["mine"], {"command": "m"})
        self.assertNotIn("gone", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["hyprland"], {"command": "hypr-mcp", "args": ["run", "hyprland"]})
        self.assertEqual(data["mcpServers"]["web"], {"httpUrl": "https://h.test"})
        self.assertEqual(data["mcpServers"]["ev"], {"url": "https://s.test"})
        self.assertEqual(managed, {"hyprland", "web", "ev"})

    def test_gemini_never_overwrites_user_entry(self):
        write_json(self.settings, json.dumps({"mcpServers": {"hyprland": {"command": "mine"}}}))
        with contextlib.redirect_stderr(io.StringIO()):
            managed = mcp_sync.sync_gemini({"hyprland": stdio("hyprland")}, set(), self.settings)
        self.assertEqual(json.loads(self.settings.read_text())["mcpServers"]["hyprland"], {"command": "mine"})
        self.assertEqual(managed, set())

    def test_gemini_skipped_when_absent(self):
        with mock.patch("shutil.which", return_value=None):
            managed = mcp_sync.sync_gemini({"hyprland": stdio("hyprland")}, set(), self.settings)
        self.assertFalse(self.settings.exists())
        self.assertEqual(managed, set())


class GeminiDenyTest(unittest.TestCase):
    def test_gemini_exclude_tools(self):
        d = ServerDef(name="n8n", spec={"command": "/x/n8n"}, deny_tools=["x"])
        self.assertEqual(mcp_sync.gemini_entry(d), {"command": "hypr-mcp", "args": ["run", "n8n"], "excludeTools": ["x"]})
        self.assertNotIn("excludeTools", mcp_sync.gemini_entry(stdio("plain")))


class ClaudeRulesTest(unittest.TestCase):
    def setUp(self):
        self.settings = tmpdir(self) / ".claude" / "settings.json"

    def read(self):
        return json.loads(self.settings.read_text())

    def test_deny_rules(self):
        defs = {"n8n": ServerDef(name="n8n", spec={"command": "x"}, deny_tools=["a", "b"]),
                "plain": stdio("plain")}
        self.assertEqual(mcp_sync.deny_rules(defs), {"mcp__n8n__a", "mcp__n8n__b"})

    def test_deny_rules_use_claude_code_names(self):
        defs = {"home.lab": ServerDef(name="home.lab", spec={"command": "x"}, deny_tools=["bad"])}
        self.assertEqual(mcp_sync.deny_rules(defs), {"mcp__home_lab__bad"})

    def test_rules_add_and_remove_managed(self):
        write_json(self.settings, json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}, "model": "x"}))
        managed = mcp_sync.sync_claude_rules(self.settings, "deny", {"mcp__n8n__a"}, set())
        self.assertEqual(managed, {"mcp__n8n__a"})
        self.assertEqual(self.read(), {"permissions": {"deny": ["Bash(rm:*)", "mcp__n8n__a"]}, "model": "x"})
        managed = mcp_sync.sync_claude_rules(self.settings, "deny", set(), managed)
        self.assertEqual(managed, set())
        self.assertEqual(self.read(), {"permissions": {"deny": ["Bash(rm:*)"]}, "model": "x"})

    def test_rules_keep_user_entries(self):
        # A rule the user wrote is never taken over, duplicated or removed.
        write_json(self.settings, json.dumps({"permissions": {"deny": ["mcp__n8n__a"]}}))
        managed = mcp_sync.sync_claude_rules(self.settings, "deny", {"mcp__n8n__a"}, set())
        self.assertEqual(managed, set())
        self.assertEqual(self.read()["permissions"]["deny"], ["mcp__n8n__a"])
        mcp_sync.sync_claude_rules(self.settings, "deny", set(), managed)
        self.assertEqual(self.read()["permissions"]["deny"], ["mcp__n8n__a"])

    def test_rules_keep_mode(self):
        write_json(self.settings, "{}")
        self.settings.chmod(0o600)
        mcp_sync.sync_claude_rules(self.settings, "deny", {"mcp__n8n__a"}, set())
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        new = self.settings.parent / "new" / "settings.json"
        mcp_sync.sync_claude_rules(new, "deny", {"mcp__n8n__a"}, set())
        self.assertEqual(new.stat().st_mode & 0o777, 0o600)

    def test_rules_unchanged_file_not_rewritten(self):
        write_json(self.settings, json.dumps({"permissions": {"deny": ["mcp__n8n__a"]}}))
        before = self.settings.stat().st_ino
        mcp_sync.sync_claude_rules(self.settings, "deny", {"mcp__n8n__a"}, {"mcp__n8n__a"})
        self.assertEqual(self.settings.stat().st_ino, before)

    def test_rules_skip_bad_json(self):
        write_json(self.settings, "{oops")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            managed = mcp_sync.sync_claude_rules(self.settings, "deny", {"mcp__n8n__a"}, {"mcp__old__b"})
        self.assertEqual(managed, {"mcp__old__b"})
        self.assertEqual(self.settings.read_text(), "{oops")
        self.assertIn(str(self.settings), err.getvalue())

    def test_list_shows_deny(self):
        root = tmpdir(self)
        write_json(root / "n8n.json", '{"command": "x", "readOnlyTools": ["r"], "denyTools": ["d"]}')
        out = io.StringIO()
        with mock.patch("atomic_agent.paths.registry_dirs", return_value=[root]), contextlib.redirect_stdout(out):
            self.assertEqual(mcp_sync.main(["list"]), 0)
        self.assertIn("read-only: r\tdeny: d", out.getvalue())

    def test_claude_settings_path(self):
        with mock.patch.dict(os.environ, {"HOME": "/h"}, clear=True):
            self.assertEqual(mcp_sync.claude_settings_path(), Path("/h/.claude/settings.json"))
        with mock.patch.dict(os.environ, {"HOME": "/h", "CLAUDE_CONFIG_DIR": "/c"}, clear=True):
            self.assertEqual(mcp_sync.claude_settings_path(), Path("/c/settings.json"))


def secret_def(name="n8n"):
    return ServerDef(name=name, spec={"type": "http", "url": "https://n.test/mcp",
                                      "headers": {"Authorization": {"credential": "n8n-hdr-authorization"}, "X-A": "1"}})


class SecretHeadersTest(unittest.TestCase):
    def test_secret_headers_never_in_client_entry(self):
        entry = mcp_sync.client_entry(secret_def())
        self.assertEqual(entry, {"type": "http", "url": "https://n.test/mcp", "headersHelper": "hypr-mcp headers n8n"})
        self.assertNotIn("credential", json.dumps(entry))

    def test_plain_headers_unchanged(self):
        spec = {"type": "http", "url": "https://x.test", "headers": {"A": "b"}}
        self.assertEqual(mcp_sync.client_entry(ServerDef(name="w", spec=spec)), spec)
        self.assertFalse(mcp_sync.has_secret_headers(ServerDef(name="w", spec=spec)))
        self.assertTrue(mcp_sync.has_secret_headers(secret_def()))

    def test_gemini_skips_secret_header_server(self):
        settings = tmpdir(self) / ".gemini" / "settings.json"
        write_json(settings, json.dumps({"mcpServers": {"n8n": {"httpUrl": "https://old"}}}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            managed = mcp_sync.sync_gemini({"n8n": secret_def(), "hyprland": stdio("hyprland")}, {"n8n"}, settings)
        servers = json.loads(settings.read_text())["mcpServers"]
        self.assertNotIn("n8n", servers)
        self.assertIn("hyprland", servers)
        self.assertEqual(managed, {"hyprland"})
        self.assertEqual(err.getvalue().count("n8n"), 1)
        self.assertNotIn("credential", settings.read_text())

    def registry_with_n8n(self):
        root = tmpdir(self)
        write_json(root / "n8n.json", json.dumps(secret_def().spec))
        write_json(root / "local.json", '{"command": "/x"}')
        return [root]

    def test_headers_prints_resolved(self):
        out = io.StringIO()
        with mock.patch("atomic_agent.mcp_sync.resolve_env", return_value={"Authorization": "Bearer t0k", "X-A": "1"}) as res, \
             contextlib.redirect_stdout(out):
            rc = mcp_sync.print_headers("n8n", self.registry_with_n8n())
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), {"Authorization": "Bearer t0k", "X-A": "1"})
        res.assert_called_once_with(secret_def().spec["headers"])

    def test_headers_secret_error(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("atomic_agent.mcp_sync.resolve_env", side_effect=SecretError("Authorization: lookup failed")), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mcp_sync.print_headers("n8n", self.registry_with_n8n())
        self.assertEqual(rc, 3)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Authorization", err.getvalue())

    def test_headers_unknown_or_stdio(self):
        dirs = self.registry_with_n8n()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mcp_sync.print_headers("nope", dirs), 2)
            self.assertEqual(mcp_sync.print_headers("local", dirs), 2)

    def test_main_headers_verb(self):
        with mock.patch("atomic_agent.paths.registry_dirs", return_value=["d"]), \
             mock.patch("atomic_agent.mcp_sync.print_headers", return_value=0) as ph:
            self.assertEqual(mcp_sync.main(["headers", "n8n"]), 0)
        ph.assert_called_once_with("n8n", ["d"])


class RunTest(unittest.TestCase):
    def test_run_execs_with_resolved_env(self):
        root = tmpdir(self)
        write_json(root / "user" / "s.json", '{"command": "/bin/srv", "args": ["-x"], "env": {"A": "1", "T": {"keyring": {"service": "s", "account": "a"}}}}')
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin", "KEEP": "k"}, clear=True), \
             mock.patch("atomic_agent.mcp_sync.resolve_env", return_value={"A": "1", "T": "tok"}), \
             mock.patch("os.execvpe") as execvpe:
            mcp_sync.run_server("s", [root / "share", root / "user"])
        cmd, argv, env = execvpe.call_args.args
        self.assertEqual((cmd, argv), ("/bin/srv", ["/bin/srv", "-x"]))
        self.assertEqual((env["A"], env["T"], env["KEEP"]), ("1", "tok", "k"))

    def test_run_unknown_server_fails(self):
        root = tmpdir(self)
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()):
            mcp_sync.run_server("nope", [root])
        self.assertNotEqual(cm.exception.code, 0)


class ManagedStateTest(unittest.TestCase):
    def test_round_trip(self):
        f = tmpdir(self) / "state" / "m.json"
        self.assertEqual(mcp_sync.load_managed(f), {"claude": set(), "gemini": set(), "claude_deny": set()})
        mcp_sync.save_managed(f, {"claude": {"b", "a"}, "gemini": set(), "claude_deny": {"mcp__n8n__a"}})
        self.assertEqual(json.loads(f.read_text()), {"claude": ["a", "b"], "gemini": [], "claude_deny": ["mcp__n8n__a"]})
        self.assertEqual(mcp_sync.load_managed(f)["claude"], {"a", "b"})



class HardeningTest(unittest.TestCase):
    """Fixes from the piece 3 final review (deferred minors)."""

    def setUp(self):
        self.root = tmpdir(self)
        self.settings = self.root / ".claude" / "settings.json"

    def read(self):
        return json.loads(self.settings.read_text())

    def test_headers_helper_name_is_shell_quoted(self):
        self.assertEqual(mcp_sync.client_entry(secret_def())["headersHelper"], "hypr-mcp headers n8n")
        odd = mcp_sync.client_entry(secret_def("a b;id"))["headersHelper"]
        self.assertEqual(odd, "hypr-mcp headers 'a b;id'")

    def test_headers_strip_trailing_newlines(self):
        out = io.StringIO()
        with mock.patch("atomic_agent.mcp_sync.resolve_env", return_value={"Authorization": "Bearer t\n", "X-A": "1\r\n"}), \
             contextlib.redirect_stdout(out):
            root = tmpdir(self)
            write_json(root / "n8n.json", json.dumps(secret_def().spec))
            self.assertEqual(mcp_sync.print_headers("n8n", [root]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"Authorization": "Bearer t", "X-A": "1"})

    def test_rules_write_through_symlink(self):
        target = write_json(self.root / "dotfiles" / "settings.json", "{}")
        self.settings.parent.mkdir(parents=True)
        self.settings.symlink_to(target)
        mcp_sync.sync_claude_rules(self.settings, "deny", {"mcp__n8n__a"}, set())
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(json.loads(target.read_text())["permissions"]["deny"], ["mcp__n8n__a"])

    def test_rules_drop_list_they_emptied(self):
        write_json(self.settings, json.dumps({"permissions": {"deny": ["mcp__n8n__a"]}, "model": "x"}))
        mcp_sync.sync_claude_rules(self.settings, "deny", set(), {"mcp__n8n__a"})
        self.assertEqual(self.read(), {"model": "x"})
        write_json(self.settings, json.dumps({"permissions": {"deny": ["mcp__n8n__a"], "allow": ["Read"]}}))
        mcp_sync.sync_claude_rules(self.settings, "deny", set(), {"mcp__n8n__a"})
        self.assertEqual(self.read(), {"permissions": {"allow": ["Read"]}})

    def test_rules_keep_non_ascii(self):
        write_json(self.settings, json.dumps({"model": "caf\u00e9"}))
        mcp_sync.sync_claude_rules(self.settings, "deny", {"mcp__n8n__a"}, set())
        self.assertIn("caf\u00e9", self.settings.read_text(encoding="utf-8"))

    def test_gemini_non_object_settings_left_alone(self):
        settings = write_json(self.root / ".gemini" / "settings.json", "[]")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            managed = mcp_sync.sync_gemini({"hyprland": stdio("hyprland")}, {"old"}, settings)
        self.assertEqual(managed, {"old"})
        self.assertEqual(settings.read_text(), "[]")
        self.assertIn(str(settings), err.getvalue())

    def test_main_saves_each_step_before_a_later_one_fails(self):
        state = self.root / "state" / "mcp-managed.json"
        with mock.patch("atomic_agent.paths.registry_dirs", return_value=[self.root / "none"]), \
             mock.patch("atomic_agent.paths.managed_file", return_value=state), \
             mock.patch("shutil.which", return_value="/usr/bin/claude"), \
             mock.patch("atomic_agent.mcp_sync.sync_claude", return_value={"hyprland"}), \
             mock.patch("atomic_agent.mcp_sync.sync_claude_rules", return_value={"mcp__n8n__a"}), \
             mock.patch("atomic_agent.mcp_sync.sync_gemini", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                mcp_sync.main(["sync"])
        saved = json.loads(state.read_text())
        self.assertEqual(saved["claude"], ["hyprland"])
        self.assertEqual(saved["claude_deny"], ["mcp__n8n__a"])


class DenyFirstTest(unittest.TestCase):
    """sync_claude runs `claude mcp` once per server (~20 s on frmwrk). A deny rule that
    another writer dropped must be back before that, not after it."""

    def setUp(self):
        self.root = tmpdir(self)
        self.settings = self.root / ".claude" / "settings.json"
        self.state = self.root / "state" / "mcp-managed.json"
        self.reg = self.root / "mcp.d"
        write_json(self.reg / "n8n.json", json.dumps(
            {"type": "http", "url": "https://n.test/mcp", "denyTools": ["run"]}))
        self.seen = None

    def denies(self):
        return json.loads(self.settings.read_text()).get("permissions", {}).get("deny", [])

    def run_main(self):
        def fake_sync_claude(defs, managed, run=None):
            self.seen = self.denies()  # what Claude Code holds during the round-trip
            return managed
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / ".claude"), "HOME": str(self.root)}), \
             mock.patch("atomic_agent.paths.registry_dirs", return_value=[self.reg]), \
             mock.patch("atomic_agent.paths.managed_file", return_value=self.state), \
             mock.patch("shutil.which", return_value="/usr/bin/claude"), \
             mock.patch("atomic_agent.mcp_sync.sync_claude", side_effect=fake_sync_claude):
            self.assertEqual(mcp_sync.main(["sync"]), 0)

    def test_dropped_deny_rule_is_back_before_the_client_round_trip(self):
        write_json(self.settings, json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}}))
        write_json(self.state, json.dumps({"claude_deny": ["mcp__n8n__run"]}))
        self.run_main()
        self.assertIn("mcp__n8n__run", self.seen)
        self.assertEqual(self.denies(), ["Bash(rm:*)", "mcp__n8n__run"])

    def test_removed_server_keeps_its_rules_until_its_entry_is_gone(self):
        (self.reg / "n8n.json").unlink()
        write_json(self.settings, json.dumps({"permissions": {"deny": ["mcp__n8n__run"]}}))
        write_json(self.state, json.dumps({"claude": ["n8n"], "claude_deny": ["mcp__n8n__run"]}))
        self.run_main()
        self.assertEqual(self.seen, ["mcp__n8n__run"])
        self.assertNotIn("permissions", json.loads(self.settings.read_text()))
        self.assertEqual(json.loads(self.state.read_text())["claude_deny"], [])


if __name__ == "__main__":
    unittest.main()
