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

    def test_decide_always_saves_both_forms_for_a_linked_home(self):
        # The bootc layout: the user's home is a link (/home/u -> /var/home/u).
        real = self.root / "var" / "home" / "u"
        (real / "Code").mkdir(parents=True)
        link = self.root / "home" / "u"
        link.parent.mkdir()
        link.symlink_to(real)
        with mock.patch.dict(os.environ, {"HOME": str(link), "PATH": "/usr/bin"}):
            approvals.decide("Edit", {"file_path": f"{link}/Code/a.py"}, ask=lambda card, session: "always")
        rules = json.loads((self.root / "cfg/atomic-hyprland/agent/permissions.json").read_text())
        self.assertEqual(rules["permissions"]["allow"], [f"Edit(/{link}/Code/a.py)", f"Edit(/{real}/Code/a.py)"])

    def test_decide_saves_the_forms_checked_when_the_card_was_built(self):
        # TOCTOU: while the card waits for an answer, the agent could repoint a link
        # (~/Code -> ~/.config/systemd/user). What gets saved must be what was checked.
        real = self.root / "var" / "home" / "u"
        (real / "Code").mkdir(parents=True)
        (real / ".config" / "systemd" / "user").mkdir(parents=True)
        link = self.root / "home" / "u"
        link.parent.mkdir()
        link.symlink_to(real)

        def ask_after_retargeting(card, session):
            (real / "Code").rename(real / "Code.orig")
            (real / "Code").symlink_to(real / ".config" / "systemd" / "user")
            return "always"

        with mock.patch.dict(os.environ, {"HOME": str(link), "PATH": "/usr/bin"}):
            approvals.decide("Edit", {"file_path": f"{link}/Code/a.service"}, ask=ask_after_retargeting)
        allow = json.loads((self.root / "cfg/atomic-hyprland/agent/permissions.json").read_text())["permissions"]["allow"]
        self.assertEqual(allow, [f"Edit(/{link}/Code/a.service)", f"Edit(/{real}/Code/a.service)"])
        self.assertFalse(any(".config" in r for r in allow))

    def test_decide_deny_shape(self):
        out = approvals.decide("Bash", {"command": "id"}, ask=lambda card, session: "deny")
        self.assertEqual(out, {"behavior": "deny", "message": "Denied by the user"})

    def test_decide_question_returns_answers(self):
        inp = {"questions": [{"question": "Which service?", "header": "S", "options": []}]}
        out = approvals.decide("AskUserQuestion", inp,
                               ask=lambda c, s: json.dumps({"answers": {"Which service?": "waybar"}}))
        self.assertEqual(out, {"behavior": "allow",
                               "updatedInput": {**inp, "answers": {"Which service?": "waybar"}}})

    def test_decide_question_skipped(self):
        out = approvals.decide("AskUserQuestion", {"questions": []}, ask=lambda c, s: "deny")
        self.assertEqual(out["behavior"], "deny")
        self.assertIn("skipped", out["message"])

    def test_decide_answer_json_never_allows_other_tools(self):
        out = approvals.decide("Bash", {"command": "id"}, ask=lambda c, s: json.dumps({"answers": {}}))
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
