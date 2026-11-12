import json
import os
import unittest
from unittest import mock

from atomic_agent.servers import approvals
from helpers import tmpdir, write_json


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        env = {"HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / "cfg"),
               "XDG_RUNTIME_DIR": str(self.root / "run"), "HYPR_AGENT_SESSION": "s1",
               "ATOMIC_AGENT_SHARE": str(self.root / "share"), "ATOMIC_AGENT_ETC": str(self.root / "etc")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start(); self.addCleanup(p.stop)
        write_json(self.root / "share" / "system.json",
                   '{"command": "x", "rootTools": ["bootc_rollback"], "toolNotes": {"bootc_rollback": "Roll back again."}}')

    def test_decide_always_writes_rule(self):
        cmd = {"command": "systemctl --user restart waybar"}
        out = approvals.decide("Bash", cmd, ask=lambda card, session: "always")
        self.assertEqual(out, {"behavior": "allow", "updatedInput": cmd})
        rules = json.loads((self.root / "cfg/atomic-hyprland/agent/permissions.json").read_text())
        self.assertEqual(rules["permissions"]["allow"], ["Bash(systemctl --user restart waybar)"])
        approvals.decide("Bash", cmd, ask=lambda card, session: "always")
        rules = json.loads((self.root / "cfg/atomic-hyprland/agent/permissions.json").read_text())
        self.assertEqual(len(rules["permissions"]["allow"]), 1)

    def test_decide_deny_shape(self):
        out = approvals.decide("Bash", {"command": "id"}, ask=lambda card, session: "deny")
        self.assertEqual(out, {"behavior": "deny", "message": "Denied by the user"})

    def test_decide_allow_passes_input(self):
        inp = {"file_path": "/h/a", "content": "x"}
        self.assertEqual(approvals.decide("Write", inp, ask=lambda c, s: "allow"),
                         {"behavior": "allow", "updatedInput": inp})

    def test_root_tool_card_has_no_rule_and_registry_note(self):
        seen = {}
        def ask(card, session):
            seen["card"], seen["session"] = card, session
            return "always"
        out = approvals.decide("mcp__system__bootc_rollback", {}, ask=ask)
        self.assertIsNone(seen["card"].rule)
        self.assertEqual(seen["card"].undo, "Roll back again.")
        self.assertEqual(seen["session"], "s1")
        # "always" on a card that offers no rule is treated as a one-time allow
        self.assertEqual(out["behavior"], "allow")
        self.assertFalse((self.root / "cfg/atomic-hyprland/agent/permissions.json").exists())


if __name__ == "__main__":
    unittest.main()
