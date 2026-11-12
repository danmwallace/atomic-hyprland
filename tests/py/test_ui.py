import json
import os
import threading
import time
import unittest
from pathlib import Path
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
        self.assertIn("-D allow_markup=false", argv)
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

    def test_card_body_shows_note_as_agents_words(self):
        body = ui.card_body({"detail": "rm x", "undo": "u", "note": "tidy up"})
        self.assertIn("Agent's note: tidy up", body)

    def test_card_body_uses_preview(self):
        body = ui.card_body({"detail": "--- a\n+++ b\n", "preview": "/h/a.conf (+1 −1 lines)", "undo": "u"})
        self.assertTrue(body.startswith("/h/a.conf (+1 −1 lines)"))
        self.assertNotIn("+++", body)
        self.assertIn("Click to answer (or Super+Y).", body)

    def test_details_text_says_who_does_what(self):
        text = ui.details_text({"title": "The agent wants to run a command", "summary": "id",
                                "detail": "id", "undo": "Can't be undone automatically.", "note": "check"})
        self.assertTrue(text.startswith("The agent wants to run a command"))
        self.assertIn("Allow lets the agent do this now. Deny blocks it", text)
        self.assertIn("Agent's note: check", text)

    def question_card(self):
        q = {"question": "Which service?", "header": "Service", "multiSelect": False,
             "options": [{"label": "waybar", "description": "The bar"}, {"label": "mako", "description": ""}]}
        return Card(title="The agent has a question", detail="", undo="", rule=None,
                    summary="Which service?", questions=[q])

    def test_review_question_answers_with_label(self):
        stub(self.bin, "wofi", f'cat > "{self.root}/menu.txt"; echo "waybar — The bar"')
        pid = ui.new_pending(self.question_card(), "s1")
        ui.review(pid)
        menu = (self.root / "menu.txt").read_text().splitlines()
        self.assertEqual(menu, ["waybar — The bar", "mako", ui.SKIP])
        self.assertEqual(json.loads(ui.wait_answer(pid, timeout=1, poll=0.02)),
                         {"answers": {"Which service?": "waybar"}})

    def test_question_menu_lines_stay_one_line(self):
        q = {"question": "Pick", "options": [{"label": "a\nAllow", "description": "x\ny"}]}
        stub(self.bin, "wofi", f'cat > "{self.root}/menu.txt"; exit 1')
        pid = ui.new_pending(Card(title="q", detail="", undo="", rule=None, questions=[q]), "s1")
        ui.review(pid)
        self.assertEqual((self.root / "menu.txt").read_text().splitlines(), ["a Allow — x y", ui.SKIP])

    def test_review_question_skip_denies(self):
        self.wofi_picks("Skip")
        pid = ui.new_pending(self.question_card(), "s1")
        ui.review(pid)
        self.assertEqual(ui.wait_answer(pid, timeout=1, poll=0.02), "deny")

    def test_review_question_escape_leaves_it_pending(self):
        self.wofi_picks(None)
        pid = ui.new_pending(self.question_card(), "s1")
        ui.review(pid)
        self.assertEqual(ui.oldest_pending(), pid)

    def test_plain_summary(self):
        md = "**Nothing** is broken. The `terminal` shows:\n\n```\nUnit x not found.\n```\n\n## Next\n- run it"
        self.assertEqual(ui.plain_summary(md),
                         "Nothing is broken. The terminal shows:\n\n  Unit x not found.\n\nNext\n- run it")
        long = "word " * 200
        out = ui.plain_summary(long, limit=50)
        self.assertLessEqual(len(out), 51)
        self.assertTrue(out.endswith("…"))

    def test_choose_view_opens_pager_then_menu_again(self):
        stub(self.bin, "notify-send", "echo 7; echo default")
        picks, shown = iter(["Read the full answer", "Fix it"]), []
        key = ui.choose("Agent", "short", [("read", "Read the full answer"), ("fix", "Fix it")],
                        menu=lambda prompt, lines: next(picks), views={"read": "the whole answer"},
                        pager=shown.append)
        self.assertEqual((key, shown), ("fix", ["the whole answer"]))

    def test_answers_open_in_glow(self):
        stub(self.bin, "hypr-terminal", "")
        with mock.patch.object(ui.shutil, "which", return_value="/usr/bin/glow"):
            ui.show_markdown("# Title\n**bold**")
        argv = self.log.read_text().splitlines()[0].split()
        self.assertEqual(argv[:4], ["hypr-terminal", "-e", "/usr/bin/glow", "-p"])
        page = Path(argv[-1])
        self.assertEqual(page.suffix, ".md")
        self.assertEqual(page.read_text(), "# Title\n**bold**")

    def test_answers_fall_back_to_plain_text_without_glow(self):
        stub(self.bin, "hypr-terminal", "")
        with mock.patch.object(ui.shutil, "which", return_value=None):
            ui.show_markdown("# Title\n**bold** " + "word " * 200)
        argv = self.log.read_text().splitlines()[0].split()
        self.assertEqual(argv[:3], ["hypr-terminal", "-e", "less"])
        text = Path(argv[-1]).read_text()
        self.assertTrue(text.startswith("Title\nbold word"))
        self.assertNotIn("…", text)  # the whole answer, not the card's cut

    def test_approval_details_never_rendered_as_markdown(self):
        # Details must show the exact command: markdown would eat *, _, # and <tags>.
        stub(self.bin, "hypr-terminal", "")
        picks = iter([ui.DETAILS, None])
        pid = ui.new_pending(Card(title="t", detail="rm *.log  # <b>x</b>", undo="u", rule=None), "s1")
        with mock.patch.object(ui.shutil, "which", return_value="/usr/bin/glow"):
            ui.review(pid, menu=lambda prompt, lines: next(picks))
        argv = self.log.read_text().splitlines()[0].split()
        self.assertEqual(argv[:3], ["hypr-terminal", "-e", "less"])
        self.assertIn("rm *.log  # <b>x</b>", Path(argv[-1]).read_text())

    def test_choose_views_open_as_markdown(self):
        self.assertIs(ui.choose.__defaults__[-1], ui.show_markdown)

    def test_show_card_records_id_while_open(self):
        # I1: notify-send -p prints the id at once and keeps running until the card is answered.
        stub(self.bin, "notify-send", "echo 77; sleep 2")
        pid = ui.new_pending(CARD, "s1")
        ui.show_card(pid)
        deadline = time.time() + 1.5
        while time.time() < deadline and (ui.read_pending(pid) or {}).get("notification") != "77":
            time.sleep(0.02)
        self.assertEqual(ui.read_pending(pid)["notification"], "77")
        closed = []
        with mock.patch.object(ui, "close_card", side_effect=closed.append):
            ui.answer(pid, "allow")
            self.assertEqual(ui.wait_answer(pid, timeout=1, poll=0.02), "allow")
        self.assertEqual(closed, ["77"])

    def test_late_worker_write_does_not_recreate_pending(self):
        pid = ui.new_pending(CARD, "s1")
        ui.answer(pid, "deny")
        ui.wait_answer(pid, timeout=1, poll=0.02)
        ui._record_notification(pid, "5")
        self.assertEqual(list(ui.paths.pending_dir().iterdir()), [])

    def test_choose_card_does_not_expire(self):
        # I2: the answer and done cards stay until acted on (Fix it / Undo live there).
        stub(self.bin, "notify-send", "echo 7")
        ui.choose("Agent", "x", [("fix", "Fix it")])
        self.assertIn(" -t 0 ", " " + self.log.read_text() + " ")

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
