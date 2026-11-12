import subprocess
import unittest

from atomic_agent import prtarget
from helpers import tmpdir


class PrTargetTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.source = self.root / "image-source"
        self.conf = self.root / "agent.conf"

    def test_source_file(self):
        self.source.write_text("https://github.com/danmwallace/atomic-hyprland\n")
        self.assertEqual(prtarget.target_repo(self.source, self.conf), "danmwallace/atomic-hyprland")

    def test_conf_overrides_source(self):
        self.source.write_text("https://github.com/danmwallace/atomic-hyprland\n")
        self.conf.write_text("# PRs go to my fork\nrepo = someone/my-hyprland\n")
        self.assertEqual(prtarget.target_repo(self.source, self.conf), "someone/my-hyprland")

    def test_normalises_url(self):
        for raw in ("https://github.com/a/b", "https://github.com/a/b.git", "git@github.com:a/b.git", "a/b", "github.com/a/b/"):
            self.assertEqual(prtarget.normalise(raw), "a/b", raw)
        self.assertIsNone(prtarget.normalise("not a repo"))

    def test_missing_everything(self):
        self.assertIsNone(prtarget.target_repo(self.source, self.conf))

    def test_cannot_push_disables(self):
        no = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "false\n", "")
        yes = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "true\n", "")
        err = lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "HTTP 404")
        self.assertFalse(prtarget.can_push("a/b", run=no))
        self.assertTrue(prtarget.can_push("a/b", run=yes))
        self.assertFalse(prtarget.can_push("a/b", run=err))
        calls = []
        prtarget.can_push("a/b", run=lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "true", ""))
        self.assertEqual(calls[0], ["gh", "api", "repos/a/b", "--jq", ".permissions.push"])


if __name__ == "__main__":
    unittest.main()
