import unittest

from atomic_agent import policy


class RuleTest(unittest.TestCase):
    def test_rule_bash_prefix(self):
        self.assertEqual(policy.always_rule("Bash", {"command": "systemctl --user restart waybar"}),
                         "Bash(systemctl --user restart waybar)")

    def test_rule_is_exact_not_prefix(self):
        # A prefix rule would also allow `find . -name x -delete` after approving `find . -name x`.
        self.assertEqual(policy.always_rule("Bash", {"command": "find . -name x"}), "Bash(find . -name x)")

    def test_rule_none_for_background_and(self):
        self.assertIsNone(policy.always_rule("Bash", {"command": "sleep 1 & rm -rf x"}))

    def test_rule_mcp_tool(self):
        self.assertEqual(policy.always_rule("mcp__hyprland__focus_window", {"address": "0x1"}),
                         "mcp__hyprland__focus_window")

    def test_rule_edit_absolute_path(self):
        # Claude Code rules: //path is absolute; one Edit rule covers every file-editing tool.
        self.assertEqual(policy.always_rule("Write", {"file_path": "/home/u/.config/waybar/local.css", "content": "x"}),
                         "Edit(//home/u/.config/waybar/local.css)")
        self.assertEqual(policy.always_rule("Edit", {"file_path": "/home/u/a"}), "Edit(//home/u/a)")

    def test_rule_none_for_compound_bash(self):
        for cmd in ("make && make install", "ls; id", "cat a | tee b", "echo $(id)", "echo hi > f"):
            self.assertIsNone(policy.always_rule("Bash", {"command": cmd}), cmd)

    def test_rule_edit_refuses_globs_and_dotdot(self):
        for p in ("/home/u/*.conf", "/home/u/a?", "/home/u/[ab]", "/home/u/{a,b}", "/home/u/x/../y"):
            self.assertIsNone(policy.always_rule("Edit", {"file_path": p}), p)

    def test_rule_edit_refuses_sensitive_files(self):
        home = "/home/u"
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"HOME": home}):
            for p in (".bashrc", ".bash_profile", ".profile", ".zshrc", ".config/elvish/rc.elv",
                      ".ssh/authorized_keys", ".config/atomic-hyprland/agent/permissions.json",
                      ".config/atomic-hyprland/mcp.d/x.json", ".claude/settings.json",
                      ".config/systemd/user/evil.service", ".config/autostart/x.desktop",
                      ".config/uwsm/env-hyprland"):
                self.assertIsNone(policy.always_rule("Edit", {"file_path": f"{home}/{p}"}), p)
            self.assertEqual(policy.always_rule("Edit", {"file_path": f"{home}/.config/waybar/local.css"}),
                             f"Edit(/{home}/.config/waybar/local.css)")

    def test_rule_none_for_root_tool(self):
        self.assertIsNone(policy.always_rule("mcp__system__restart_unit", {}, {"mcp__system__restart_unit"}))


class NeverAlwaysTest(unittest.TestCase):
    def never(self, cmd):
        return policy.never_always("Bash", {"command": cmd}, set())

    def test_never_always_git_push(self):
        self.assertTrue(self.never("git push origin agent/fix"))
        self.assertTrue(self.never("gh pr create --fill"))
        self.assertFalse(self.never("git status"))
        self.assertTrue(self.never("git -C /repo push origin main"))
        self.assertTrue(self.never("git -c user.name=x --git-dir=/r/.git push"))

    def test_never_always_sudo_with_env_prefix(self):
        self.assertTrue(self.never("env FOO=1 sudo systemctl restart x"))
        self.assertTrue(self.never("  FOO=1 BAR=2 pkexec true"))
        self.assertTrue(self.never("run0 id"))
        self.assertTrue(self.never("bootc status"))

    def test_never_always_rm(self):
        for cmd in ("rm -f x", "rmdir d", "shred f", "unlink f", "find . -name '*.o' -delete", "/usr/bin/rm x"):
            self.assertTrue(self.never(cmd), cmd)

    def test_never_always_any_segment(self):
        self.assertTrue(self.never("make && rm -rf build"))
        self.assertTrue(self.never("echo ok; git push"))

    def test_never_always_screen(self):
        self.assertTrue(policy.never_always("mcp__screen__capture", {}, set()))

    def test_never_always_root_tools(self):
        self.assertTrue(policy.never_always("mcp__system__bootc_rollback", {}, {"mcp__system__bootc_rollback"}))
        self.assertFalse(policy.never_always("mcp__hyprland__focus_window", {}, {"mcp__system__bootc_rollback"}))

    def test_never_always_truncating_write(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"data")
        self.addCleanup(os.unlink, f.name)
        self.assertTrue(policy.never_always("Write", {"file_path": f.name, "content": ""}, set()))
        self.assertFalse(policy.never_always("Write", {"file_path": f.name, "content": "new"}, set()))


class CardTest(unittest.TestCase):
    def test_undo_note_bash(self):
        self.assertEqual(policy.undo_note("Bash", {"command": "x"}, {}), "Can't be undone automatically.")
        self.assertEqual(policy.undo_note("Edit", {"file_path": "/a"}, {}), "Undo restores the file.")
        self.assertEqual(policy.undo_note("mcp__s__t", {}, {"mcp__s__t": "Undo with u."}), "Undo with u.")
        self.assertEqual(policy.undo_note("mcp__s__x", {}, {}), "Can't be undone automatically.")

    def test_card_edit_has_diff(self):
        card = policy.card_for("Edit", {"file_path": "/h/a.conf", "old_string": "gaps = 5\n", "new_string": "gaps = 10\n"}, {}, set())
        self.assertIn("-gaps = 5", card.detail)
        self.assertIn("+gaps = 10", card.detail)
        self.assertIn("/h/a.conf", card.title)
        self.assertEqual(card.rule, "Edit(//h/a.conf)")
        self.assertEqual(card.undo, "Undo restores the file.")

    def test_card_bash_literal_command(self):
        card = policy.card_for("Bash", {"command": "systemctl --user restart waybar", "description": "Restart the bar"}, {}, set())
        self.assertEqual(card.detail, "systemctl --user restart waybar")
        self.assertIn("Restart the bar", card.title)

    def test_card_write_head(self):
        content = "".join(f"line{i}\n" for i in range(100))
        card = policy.card_for("Write", {"file_path": "/h/new.txt", "content": content}, {}, set())
        self.assertIn("line39", card.detail)
        self.assertNotIn("line40\n", card.detail)

    def test_card_mcp_json(self):
        card = policy.card_for("mcp__hyprland__close_window", {"address": "0xabc"}, {}, set())
        self.assertIn('"address": "0xabc"', card.detail)
        self.assertIn("hyprland", card.title)


if __name__ == "__main__":
    unittest.main()
