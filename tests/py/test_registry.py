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

    def test_ask_every_time_accumulates_across_layers(self):
        write_json(self.share / "srv01-ops.json", '{"command": "x", "askEveryTime": ["a"]}')
        write_json(self.user / "srv01-ops.json", '{"command": "y", "askEveryTime": ["b"]}')
        self.assertEqual(load_registry(self.dirs)["srv01-ops"].ask_tools, ["a", "b"])

    def test_ask_in_machine_layer_beats_user_read_only(self):
        # The role writes the ask list root-owned in /etc; the user-writable file can't
        # make the tool read-only or drop it from the ask list.
        write_json(self.etc / "srv01-ops.json", '{"askEveryTime": ["vm_start"]}')
        write_json(self.user / "srv01-ops.json", '{"command": "y", "readOnlyTools": ["vm_start", "vms"]}')
        d = load_registry(self.dirs)["srv01-ops"]
        self.assertEqual(d.ask_tools, ["vm_start"])
        self.assertEqual(d.read_only_tools, ["vms"])
        self.assertNotIn("askEveryTime", d.spec)

    def test_list_only_layer_keeps_lower_definition(self):
        # A fragment holding only lists adds to them; it doesn't replace the definition.
        write_json(self.share / "srv01-ops.json", '{"command": "x", "readOnlyTools": ["vms"]}')
        write_json(self.etc / "srv01-ops.json", '{"askEveryTime": ["vm_start"]}')
        d = load_registry(self.dirs)["srv01-ops"]
        self.assertEqual(d.spec["command"], "x")
        self.assertEqual(d.ask_tools, ["vm_start"])
        self.assertEqual(d.source, self.share / "srv01-ops.json")

    def test_ask_every_time_must_be_a_list(self):
        write_json(self.share / "a.json", '{"command": "x", "askEveryTime": "vm_start"}')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertNotIn("a", load_registry(self.dirs))
        self.assertIn("askEveryTime must be a list", err.getvalue())

    def test_deny_tools_accumulate(self):
        # Like rootTools: a later (user-writable) layer cannot drop an earlier deny.
        write_json(self.share / "n8n.json", '{"command": "x", "denyTools": ["a"]}')
        write_json(self.user / "n8n.json", '{"command": "y", "denyTools": ["b", "a"]}')
        self.assertEqual(load_registry(self.dirs)["n8n"].deny_tools, ["a", "b"])

    def test_string_deny_tools_skips_file(self):
        # "denyTools": "edit" must not turn into a deny of the letters e, d, i, t.
        write_json(self.user / "n8n.json", '{"command": "x", "denyTools": "edit"}')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertNotIn("n8n", load_registry(self.dirs))
        self.assertIn("denyTools", err.getvalue())

    def test_null_list_keys_skip_file_without_crashing(self):
        for key in ("denyTools", "rootTools", "readOnlyTools"):
            write_json(self.user / "n8n.json", '{"command": "x", "%s": null}' % key)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertNotIn("n8n", load_registry(self.dirs), key)

    def test_non_string_tool_skips_file(self):
        write_json(self.user / "n8n.json", '{"command": "x", "readOnlyTools": ["a", 3]}')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertNotIn("n8n", load_registry(self.dirs))

    def test_bad_user_layer_keeps_lower_layer_deny(self):
        write_json(self.share / "n8n.json", '{"command": "x", "denyTools": ["a"]}')
        write_json(self.user / "n8n.json", '{"command": "y", "denyTools": "b"}')
        with contextlib.redirect_stderr(io.StringIO()):
            d = load_registry(self.dirs)["n8n"]
        self.assertEqual(d.deny_tools, ["a"])
        self.assertEqual(d.spec["command"], "x")

    def test_denied_tool_not_read_only(self):
        write_json(self.share / "n8n.json", '{"command": "x", "readOnlyTools": ["a", "b"], "denyTools": ["b"]}')
        self.assertEqual(load_registry(self.dirs)["n8n"].read_only_tools, ["a"])

    def test_deny_tools_not_in_spec(self):
        write_json(self.share / "n8n.json", '{"command": "x", "denyTools": ["b"]}')
        d = load_registry(self.dirs)["n8n"]
        self.assertNotIn("denyTools", d.spec)
        self.assertEqual(d.deny_tools, ["b"])

    def test_tool_rule_matches_claude_code_names(self):
        # Claude Code replaces anything outside [A-Za-z0-9_-] with "_" in both parts
        # (observed on 2.1.325: server "hypr.land v2" -> mcp__hypr_land_v2__list_workspaces).
        from atomic_agent.registry import tool_rule
        self.assertEqual(tool_rule("hypr.land v2", "list_workspaces"), "mcp__hypr_land_v2__list_workspaces")
        self.assertEqual(tool_rule("n8n", "get-workflow.v2"), "mcp__n8n__get-workflow_v2")
        self.assertEqual(tool_rule("truenas", "pool_list"), "mcp__truenas__pool_list")

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
