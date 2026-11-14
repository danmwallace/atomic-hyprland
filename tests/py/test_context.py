import json
import subprocess
import unittest
from pathlib import Path

from atomic_agent import context
from helpers import tmpdir


def fake_proc(root: Path, procs: dict[int, tuple[int, str, Path]]) -> Path:
    """procs: pid -> (ppid, comm, cwd)."""
    for pid, (ppid, comm, cwd) in procs.items():
        d = root / str(pid)
        d.mkdir(parents=True)
        (d / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1 0 -1 4194560 0 0 0 0\n")
        (d / "comm").write_text(comm + "\n")
        cwd.mkdir(parents=True, exist_ok=True)
        (d / "cwd").symlink_to(cwd)
    (root / "self").mkdir()
    return root


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)

    def test_window_geometry(self):
        self.assertEqual(context.window_geometry({"at": [10, 20], "size": [300, 200]}), "10,20 300x200")

    def test_terminal_cwd_finds_deepest_shell(self):
        proc = fake_proc(self.root / "proc", {
            100: (1, "ghostty", self.root / "home"),
            101: (100, "bash", self.root / "home"),
            102: (101, "elvish", self.root / "home/Code/app"),
            103: (102, "make", self.root / "home/Code/app/build"),
            200: (1, "bash", self.root / "other"),
        })
        self.assertEqual(context.terminal_cwd(100, proc), self.root / "home/Code/app")
        self.assertIsNone(context.terminal_cwd(999, proc))

    def test_clipboard_skips_password_hint(self):
        def run(argv, **kw):
            out = "text/plain\nx-kde-passwordManagerHint\n" if "--list-types" in argv else "hunter2"
            return subprocess.CompletedProcess(argv, 0, out, "")
        self.assertIsNone(context.clipboard_text(run=run))

    def test_clipboard_text_truncated(self):
        def run(argv, **kw):
            out = "text/plain\n" if "--list-types" in argv else "x" * 5000
            return subprocess.CompletedProcess(argv, 0, out, "")
        self.assertEqual(len(context.clipboard_text(run=run, limit=4000)), 4000)

    def test_clipboard_empty(self):
        self.assertIsNone(context.clipboard_text(run=lambda a, **k: subprocess.CompletedProcess(a, 1, "", "")))


class PromptTest(unittest.TestCase):
    def ctx(self):
        return context.Context(screenshot=Path("/s/ask.png"), clipboard="error: boom", cwd=Path("/h/app"))

    def scripted(self, *picks):
        seen = []
        it = iter(picks)
        def menu(prompt, lines):
            seen.append(list(lines))
            return next(it)
        return menu, seen

    def test_chips_say_what_is_attached(self):
        self.assertEqual(context.chip_lines(self.ctx())[1:], [
            "[x] Screenshot of this window   (select to leave out)",
            "[x] Clipboard: error: boom   (select to leave out)",
            "[x] Folder: /h/app   (select to leave out)",
        ])

    def test_left_out_chip_stays_listed_and_is_not_sent(self):
        ctx = self.ctx()
        menu, seen = self.scripted(context.chip_lines(ctx)[1], "why did make fail?")
        text, out = context.prompt(ctx, menu=menu)
        self.assertEqual(text, "why did make fail?")
        self.assertIsNone(out.screenshot)
        self.assertEqual(out.clipboard, "error: boom")
        self.assertIn("[ ] Screenshot of this window   (select to include)", seen[1])

    def test_left_out_chip_can_be_put_back(self):
        ctx = self.ctx()
        off = "[ ] Clipboard: error: boom   (select to include)"
        menu, seen = self.scripted(context.chip_lines(ctx)[2], off, "why?")
        _, out = context.prompt(ctx, menu=menu)
        self.assertEqual(out.clipboard, "error: boom")
        self.assertEqual(seen[2], seen[0])

    def test_missing_context_has_no_chip(self):
        ctx = context.Context(screenshot=None, clipboard=None, cwd=Path("/h/app"))
        self.assertEqual(context.chip_lines(ctx)[1:], ["[x] Folder: /h/app   (select to leave out)"])

    def test_prompt_escape_sends_nothing(self):
        menu, _ = self.scripted(None)
        self.assertIsNone(context.prompt(self.ctx(), menu=menu))

    def test_empty_enter_default_question(self):
        # wofi returns the highlighted line on an empty Enter: the first line is the default question
        ctx = self.ctx()
        menu, seen = self.scripted(context.chip_lines(ctx)[0])
        text, _ = context.prompt(ctx, menu=menu)
        self.assertEqual(text, context.DEFAULT_QUESTION)
        self.assertTrue(seen[0][0].startswith("Ask:"))


class CaptureTest(unittest.TestCase):
    def fake_run(self, active: dict):
        def run(argv, **kw):
            if argv[:2] == ["hyprctl", "-j"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps(active), "")
            if argv[0] == "grim":
                return subprocess.CompletedProcess(argv, 0, b"", b"")
            return subprocess.CompletedProcess(argv, 1, "", "")  # wl-paste: empty clipboard
        return run

    def test_capture_without_a_focused_window(self):
        # Right after login, or on an empty workspace, hyprctl reports no window.
        shots = tmpdir(self)
        ctx = context.capture(shots, run=self.fake_run({}))
        self.assertIsNone(ctx.screenshot)
        self.assertFalse(ctx.focused)

    def test_capture_with_a_focused_window(self):
        shots = tmpdir(self)
        ctx = context.capture(shots, run=self.fake_run({"at": [0, 0], "size": [10, 10], "class": "firefox", "pid": 1}))
        self.assertEqual(ctx.screenshot, shots / "ask.png")
        self.assertTrue(ctx.focused)


if __name__ == "__main__":
    unittest.main()
