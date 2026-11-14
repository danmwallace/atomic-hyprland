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

    def fake_gh(self, auth_rc=0, api=(0, "true\n", "")):
        """A gh stand-in: `gh auth status` exits auth_rc; `gh api` returns api."""
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            if argv[:3] == ["gh", "auth", "status"]:
                return subprocess.CompletedProcess(argv, auth_rc, "", "" if auth_rc == 0 else "The token in default is invalid.")
            return subprocess.CompletedProcess(argv, *api)
        return run, calls

    def test_push_status_ok(self):
        run, calls = self.fake_gh()
        self.assertEqual(prtarget.push_status("a/b", run=run), "ok")
        self.assertEqual(calls[0], ["gh", "auth", "status", "--hostname", "github.com"])

    def test_push_status_logged_out_skips_the_api(self):
        # A restored home can keep hosts.yml while the keyring token is gone: gh
        # names the account, but every API call fails. That is a login problem,
        # not a permission one.
        run, calls = self.fake_gh(auth_rc=1)
        self.assertEqual(prtarget.push_status("a/b", run=run), "logged-out")
        self.assertEqual(len(calls), 1)

    def test_push_status_no_push(self):
        run, _ = self.fake_gh(api=(0, "false\n", ""))
        self.assertEqual(prtarget.push_status("a/b", run=run), "no-push")

    def test_push_status_api_error(self):
        run, _ = self.fake_gh(api=(1, "", "HTTP 404: Not Found"))
        self.assertEqual(prtarget.push_status("a/b", run=run), "error")

    def test_off_message_logged_out_says_log_in_not_fork(self):
        msg = prtarget.off_message("a/b", "logged-out")
        self.assertIn("gh auth login", msg)
        self.assertNotIn("Fork", msg)

    def test_off_message_no_push_suggests_fork(self):
        msg = prtarget.off_message("a/b", "no-push")
        self.assertIn("can't push to a/b", msg)
        self.assertIn("Fork it and set repo= in /etc/atomic-hyprland/agent.conf", msg)

    def test_off_message_error_and_missing_repo(self):
        self.assertIn("couldn't check", prtarget.off_message("a/b", "error"))
        self.assertIn("the image's repository", prtarget.off_message(None, "no-push"))


if __name__ == "__main__":
    unittest.main()
