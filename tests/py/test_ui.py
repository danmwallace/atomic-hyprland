import json
import os
import threading
import time
import unittest
from unittest import mock

from atomic_agent import ui
from atomic_agent.policy import Card
from helpers import stub, tmpdir

CARD = Card(title="Restart the bar", detail="systemctl --user restart waybar",
            undo="Can't be undone automatically.", rule="Bash(systemctl --user restart waybar)")


class UiTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.bin = self.root / "bin"
        self.log = self.root / "argv.log"
        env = {"HOME": str(self.root), "XDG_RUNTIME_DIR": str(self.root / "run"),
               "PATH": f"{self.bin}:/usr/bin:/bin", "ARGV_LOG": str(self.log)}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start(); self.addCleanup(p.stop)

    def wofi_picks(self, line_prefix):
        # wofi stub: print the first stdin line starting with the prefix (empty = Escape).
        body = 'exit 1' if line_prefix is None else f'grep -m1 "^{line_prefix}" || exit 1'
        stub(self.bin, "wofi", body)

    def test_pending_ids_are_time_ordered(self):
        a = ui.new_pending(CARD, "s1")
        time.sleep(0.002)
        b = ui.new_pending(CARD, "s1")
        self.assertLess(a, b)
        data = json.loads((ui.paths.pending_dir() / f"{a}.json").read_text())
        self.assertEqual((data["title"], data["session"]), ("Restart the bar", "s1"))

    def test_wait_times_out_to_deny(self):
        pid = ui.new_pending(CARD, "s1")
        self.assertEqual(ui.wait_answer(pid, timeout=0.2, poll=0.02), "deny")
        self.assertFalse((ui.paths.pending_dir() / f"{pid}.json").exists())

    def test_pending_removed_means_deny(self):
        pid = ui.new_pending(CARD, "s1")
        threading.Timer(0.05, lambda: (ui.paths.pending_dir() / f"{pid}.json").unlink()).start()
        self.assertEqual(ui.wait_answer(pid, timeout=5, poll=0.02), "deny")

    def test_answer_after_cleanup_is_ignored(self):
        pid = ui.new_pending(CARD, "s1")
        ui.answer(pid, "allow")
        self.assertEqual(ui.wait_answer(pid, timeout=1, poll=0.02), "allow")
        ui.answer(pid, "deny")  # a late dismissal must not leave an orphan answer behind
        self.assertEqual(list(ui.paths.pending_dir().iterdir()), [])

    def test_two_pending_answered_independently(self):
        first = ui.new_pending(CARD, "s1")
        time.sleep(0.002)
        second = ui.new_pending(CARD, "s2")
        self.assertEqual(ui.oldest_pending(), first)
        ui.answer(second, "allow")
        self.assertEqual(ui.wait_answer(second, timeout=1, poll=0.02), "allow")
        self.assertEqual(ui.oldest_pending(), first)
        self.assertEqual(ui.wait_answer(first, timeout=0.1, poll=0.02), "deny")

    def test_review_allow(self):
        self.wofi_picks("Allow")
        pid = ui.new_pending(CARD, "s1")
        ui.review(pid)
        self.assertEqual(ui.wait_answer(pid, timeout=1, poll=0.02), "allow")
        argv = self.log.read_text().splitlines()[0]
        self.assertIn("--dmenu", argv)
        self.assertIn("Restart the bar", argv)

    def test_review_always(self):
        self.wofi_picks("Always allow")
        pid = ui.new_pending(CARD, "s1")
        ui.review(pid)
        self.assertEqual(ui.wait_answer(pid, timeout=1, poll=0.02), "always")

    def test_review_escape_no_answer(self):
        self.wofi_picks(None)
        pid = ui.new_pending(CARD, "s1")
        ui.review(pid)
        self.assertFalse((ui.paths.pending_dir() / f"{pid}.answer").exists())
        self.assertEqual(ui.oldest_pending(), pid)

    def test_always_hidden_when_no_rule(self):
        stub(self.bin, "wofi", f'cat > "{self.root}/menu.txt"; echo Deny')
        pid = ui.new_pending(Card(title="t", detail="d", undo="u", rule=None), "s1")
        ui.review(pid)
        menu = (self.root / "menu.txt").read_text().splitlines()
        self.assertEqual(menu[:2], ["Allow", "Deny"])
        self.assertFalse(any(l.startswith("Always") for l in menu))

    def test_choose_returns_key(self):
        stub(self.bin, "notify-send", "echo 7; echo default")
        self.wofi_picks("Fix it")
        key = ui.choose("Agent", "The bar crashed.", [("fix", "Fix it"), ("chat", "Open chat"), ("dismiss", "Dismiss")])
        self.assertEqual(key, "fix")

    def test_choose_dismissed_card(self):
        stub(self.bin, "notify-send", "echo 7")
        self.assertIsNone(ui.choose("Agent", "x", [("fix", "Fix it")]))


if __name__ == "__main__":
    unittest.main()
