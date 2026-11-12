import json
import os
import subprocess
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest import mock

from atomic_agent import ui
from atomic_agent.policy import Card
from helpers import tmpdir

SCRIPT = Path(__file__).resolve().parents[2] / "files/usr/libexec/atomic-hyprland/waybar/agent"


def load():
    loader = SourceFileLoader("waybar_agent", str(SCRIPT))
    mod = module_from_spec(spec_from_loader("waybar_agent", loader))
    loader.exec_module(mod)
    return mod


class WaybarAgentTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        p = mock.patch.dict(os.environ, {"HOME": str(self.root), "XDG_RUNTIME_DIR": str(self.root / "run")}, clear=True)
        p.start(); self.addCleanup(p.stop)
        self.m = load()
        self.units = ""

    def run_stub(self, argv, **kw):
        return subprocess.CompletedProcess(argv, 0, self.units, "")

    def test_idle_prints_empty_text(self):
        self.assertEqual(self.m.status(run=self.run_stub)["text"], "")

    def test_running_unit(self):
        self.units = "hypr-agent-01234567.service loaded active running hypr-agent run-fix\n"
        out = self.m.status(run=self.run_stub)
        self.assertEqual(out["class"], "running")
        self.assertTrue(out["text"].startswith("󱚥"))
        self.assertIn("hypr-agent-01234567", out["tooltip"])

    def test_live_ask_counts(self):
        (self.root / "run/hypr-agent").mkdir(parents=True)
        (self.root / "run/hypr-agent/ask.pid").write_text(str(os.getpid()))
        self.assertEqual(self.m.status(run=self.run_stub)["class"], "running")
        (self.root / "run/hypr-agent/ask.pid").write_text("999999999")
        self.assertEqual(self.m.status(run=self.run_stub)["text"], "")

    def test_pending_class_and_count(self):
        ui.new_pending(Card("Run: x", "x", "u", None), "s1")
        ui.new_pending(Card("Run: y", "y", "u", None), "s1")
        out = self.m.status(run=self.run_stub)
        self.assertEqual(out["class"], "pending")
        self.assertEqual(out["text"], "󱚥 2")
        self.assertIn("Run: x", out["tooltip"])

    def test_main_prints_json(self):
        with mock.patch("sys.stdout") as stdout, mock.patch.object(self.m, "status", return_value={"text": ""}):
            self.m.main()
        self.assertEqual(json.loads("".join(c.args[0] for c in stdout.write.call_args_list)), {"text": ""})


if __name__ == "__main__":
    unittest.main()
