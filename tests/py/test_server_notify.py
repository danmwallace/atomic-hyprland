import subprocess
import unittest
from unittest import mock

from atomic_agent import ui
from atomic_agent.servers import notify


class NotifyServerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def fake(argv):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        p = mock.patch.object(notify, "_run", fake)
        p.start(); self.addCleanup(p.stop)

    def test_body_escaped_for_a_markup_server(self):
        with mock.patch.object(ui, "server_renders_markup", return_value=True):
            notify.notify("Done", "<b>bold</b> & more")
        self.assertEqual(self.calls[-1][-2:], ["Done", "&lt;b&gt;bold&lt;/b&gt; &amp; more"])

    def test_bad_urgency_refused(self):
        self.assertIn("refused", notify.notify("x", urgency="loud"))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
