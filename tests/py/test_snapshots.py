import json
import os
import unittest
from unittest import mock

from atomic_agent import snapshots
from helpers import tmpdir


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.sdir = self.root / "session"
        self.f = self.root / "home" / "a.conf"
        self.f.parent.mkdir()

    def manifest(self):
        return [json.loads(l) for l in (self.sdir / "manifest.jsonl").read_text().splitlines()]

    def test_snapshot_once_per_path(self):
        self.f.write_text("v1")
        snapshots.snapshot(self.sdir, self.f)
        self.f.write_text("v2")
        snapshots.snapshot(self.sdir, self.f)
        entries = self.manifest()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], str(self.f))
        self.assertTrue(entries[0]["existed"])
        self.assertEqual((self.sdir / entries[0]["copy"]).read_text(), "v1")

    def test_undo_skips_unapplied(self):
        # I6: the hook runs before the decision; a denied edit must not be undone later.
        new = self.root / "home" / "denied.txt"
        snapshots.snapshot(self.sdir, new)
        new.write_text("the user made this later")
        self.f.write_text("v1")
        snapshots.snapshot(self.sdir, self.f)
        self.f.write_text("user edit")
        self.assertEqual(snapshots.undo(self.sdir), [])
        self.assertTrue(new.exists())
        self.assertEqual(self.f.read_text(), "user edit")
        self.assertEqual(snapshots.changed(self.sdir), [])

    def test_undo_created_file_removed(self):
        new = self.root / "home" / "new.txt"
        snapshots.snapshot(self.sdir, new)
        new.write_text("created by the agent")
        snapshots.mark_applied(self.sdir, new)
        self.assertEqual(snapshots.undo(self.sdir), [str(new)])
        self.assertFalse(new.exists())

    def test_undo_restores_first_snapshot(self):
        self.f.write_text("v1")
        snapshots.snapshot(self.sdir, self.f)
        self.f.write_text("v2")
        snapshots.snapshot(self.sdir, self.f)
        self.f.write_text("v3")
        snapshots.mark_applied(self.sdir, self.f)
        snapshots.undo(self.sdir)
        self.assertEqual(self.f.read_text(), "v1")

    def test_undo_reverse_order(self):
        b = self.root / "home" / "b"
        self.f.write_text("a1"); b.write_text("b1")
        snapshots.snapshot(self.sdir, self.f)
        snapshots.snapshot(self.sdir, b)
        snapshots.mark_applied(self.sdir, self.f)
        snapshots.mark_applied(self.sdir, b)
        self.assertEqual(snapshots.changed(self.sdir), [str(self.f), str(b)])
        self.assertEqual(snapshots.undo(self.sdir), [str(b), str(self.f)])

    def test_undo_twice_is_noop(self):
        self.f.write_text("v1")
        snapshots.snapshot(self.sdir, self.f)
        self.f.write_text("v2")
        snapshots.mark_applied(self.sdir, self.f)
        snapshots.undo(self.sdir)
        self.f.write_text("later, by hand")
        self.assertEqual(snapshots.undo(self.sdir), [])
        self.assertEqual(self.f.read_text(), "later, by hand")

    def test_undo_routes_etc(self):
        calls = []
        with open(self.sdir.mkdir(parents=True) or self.sdir / "manifest.jsonl", "w") as m:
            m.write(json.dumps({"path": "/etc/x.conf", "existed": True, "copy": "files/0"}) + "\n")
            m.write(json.dumps({"event": "applied", "path": "/etc/x.conf"}) + "\n")
        snapshots.undo(self.sdir, restore_etc=lambda p, c: calls.append((p, c)))
        self.assertEqual(calls, [("/etc/x.conf", str(self.sdir / "files/0"))])


class HookTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        p = mock.patch.dict(os.environ, {"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state")}, clear=True)
        p.start(); self.addCleanup(p.stop)

    def event(self, tool, path):
        return {"session_id": "s1", "tool_name": tool, "tool_input": {"file_path": str(path)}, "hook_event_name": "PreToolUse"}

    def test_hook_snapshots_edit(self):
        f = self.root / "x"; f.write_text("orig")
        self.assertEqual(snapshots.hook_pre_tool_use(self.event("Edit", f)), 0)
        sdir = self.root / "state/atomic-hyprland/agent/s1"
        self.assertEqual((sdir / "files/0").read_text(), "orig")

    def test_hook_blocks_when_snapshot_fails(self):
        f = self.root / "locked"; f.write_text("secret"); f.chmod(0)
        self.addCleanup(f.chmod, 0o600)
        if os.access(f, os.R_OK):
            self.skipTest("running as root")
        self.assertEqual(snapshots.hook_pre_tool_use(self.event("Write", f)), 2)

    def test_hook_ignores_bash(self):
        ev = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "rm x"}}
        self.assertEqual(snapshots.hook_pre_tool_use(ev), 0)
        self.assertFalse((self.root / "state").exists())

    def test_hook_refuses_etc(self):
        # I3: Edit cannot write /etc as the user anyway; the system tool asks after the card.
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(snapshots.hook_pre_tool_use(self.event("Edit", "/etc/hosts")), 2)
        self.assertIn("write_etc_file", err.getvalue())
        self.assertFalse((self.root / "state").exists())

    def test_hook_fails_closed(self):
        # I7: any error blocks the edit, so nothing changes without an undo copy.
        import io, contextlib
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(snapshots.hook_pre_tool_use({"tool_name": "Edit", "tool_input": {"file_path": "/h/x"}}), 2)
            sdir = self.root / "state/atomic-hyprland/agent/s1"
            sdir.mkdir(parents=True)
            (sdir / "manifest.jsonl").write_text("{not json\n")
            f = self.root / "x"; f.write_text("a")
            self.assertEqual(snapshots.hook_pre_tool_use(self.event("Edit", f)), 2)

    def test_post_hook_marks_applied(self):
        f = self.root / "x"; f.write_text("orig")
        snapshots.hook_pre_tool_use(self.event("Edit", f))
        sdir = self.root / "state/atomic-hyprland/agent/s1"
        self.assertEqual(snapshots.changed(sdir), [])
        ev = dict(self.event("Edit", f), hook_event_name="PostToolUse")
        self.assertEqual(snapshots.hook_post_tool_use(ev), 0)
        self.assertEqual(snapshots.changed(sdir), [str(f)])
        snapshots.hook_post_tool_use(ev)
        self.assertEqual(snapshots.changed(sdir), [str(f)])


if __name__ == "__main__":
    unittest.main()
