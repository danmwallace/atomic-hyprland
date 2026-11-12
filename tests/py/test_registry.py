import contextlib
import io
import unittest

from atomic_agent.registry import load_registry
from helpers import tmpdir, write_json


class RegistryTest(unittest.TestCase):
    def setUp(self):
        root = tmpdir(self)
        self.share, self.etc, self.user = root / "share", root / "etc", root / "user"
        self.dirs = [self.share, self.etc, self.user]

    def test_later_dir_overrides(self):
        write_json(self.share / "a.json", '{"command": "x"}')
        write_json(self.user / "a.json", '{"command": "y"}')
        reg = load_registry(self.dirs)
        self.assertEqual(reg["a"].spec["command"], "y")
        self.assertEqual(reg["a"].source, self.user / "a.json")

    def test_disabled_removes(self):
        write_json(self.share / "a.json", '{"command": "x"}')
        write_json(self.user / "a.json", '{"disabled": true}')
        self.assertNotIn("a", load_registry(self.dirs))

    def test_read_only_tools(self):
        write_json(self.share / "a.json", '{"command": "x", "readOnlyTools": ["list"]}')
        write_json(self.share / "b.json", '{"command": "x"}')
        reg = load_registry(self.dirs)
        self.assertEqual(reg["a"].read_only_tools, ["list"])
        self.assertEqual(reg["b"].read_only_tools, [])

    def test_tool_notes_and_root_tools(self):
        write_json(self.share / "a.json",
                   '{"command": "x", "toolNotes": {"t": "Undo with y."}, "rootTools": ["t"], "readOnlyTools": []}')
        write_json(self.share / "b.json", '{"command": "x"}')
        reg = load_registry(self.dirs)
        self.assertEqual(reg["a"].tool_notes, {"t": "Undo with y."})
        self.assertEqual(reg["a"].root_tools, ["t"])
        self.assertEqual(reg["b"].tool_notes, {})
        self.assertEqual(reg["b"].root_tools, [])
        for key in ("toolNotes", "rootTools", "readOnlyTools", "disabled"):
            self.assertNotIn(key, reg["a"].spec)

    def test_root_tools_survive_override(self):
        # A later layer replaces the definition but cannot declassify a root tool:
        # rootTools accumulate across layers, and a root tool is never read-only.
        write_json(self.share / "system.json", '{"command": "x", "rootTools": ["restart_unit"], "readOnlyTools": ["journal"]}')
        write_json(self.user / "system.json", '{"command": "y", "readOnlyTools": ["journal", "restart_unit"]}')
        d = load_registry(self.dirs)["system"]
        self.assertEqual(d.spec["command"], "y")
        self.assertEqual(d.root_tools, ["restart_unit"])
        self.assertEqual(d.read_only_tools, ["journal"])

    def test_invalid_file_skipped(self):
        write_json(self.share / "bad.json", "{not json")
        write_json(self.share / "empty.json", '{"args": ["x"]}')
        write_json(self.share / "ok.json", '{"command": "x"}')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            reg = load_registry(self.dirs)
        self.assertEqual(sorted(reg), ["ok"])
        self.assertIn("bad.json", err.getvalue())
        self.assertIn("empty.json", err.getvalue())

    def test_url_server(self):
        write_json(self.etc / "web.json", '{"type": "http", "url": "https://x.test/mcp", "headers": {"A": "b"}}')
        reg = load_registry(self.dirs)
        self.assertEqual(reg["web"].spec, {"type": "http", "url": "https://x.test/mcp", "headers": {"A": "b"}})

    def test_non_json_files_ignored(self):
        write_json(self.share / "README.md", "hi")
        write_json(self.share / "a.json", '{"command": "x"}')
        self.assertEqual(sorted(load_registry(self.dirs)), ["a"])

    def test_missing_dirs_ok(self):
        self.assertEqual(load_registry(self.dirs), {})


if __name__ == "__main__":
    unittest.main()
