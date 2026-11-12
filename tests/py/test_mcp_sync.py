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
        self.assertEqual(mcp_sync.load_managed(f), {"claude": set(), "gemini": set()})
        mcp_sync.save_managed(f, {"claude": {"b", "a"}, "gemini": set()})
        self.assertEqual(json.loads(f.read_text()), {"claude": ["a", "b"], "gemini": []})
        self.assertEqual(mcp_sync.load_managed(f)["claude"], {"a", "b"})


if __name__ == "__main__":
    unittest.main()
