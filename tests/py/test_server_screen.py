import json
import os
import subprocess
import unittest
from unittest import mock

from atomic_agent.servers import screen
from helpers import tmpdir

CLIENTS = json.dumps([{"address": "0xabc", "at": [10, 20], "size": [300, 200]},
                      {"address": "0xdef", "at": [0, 0], "size": [5, 5]}])


class ScreenTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.calls = []
        def fake(argv):
            self.calls.append(argv)
            out = CLIENTS if argv[:3] == ["hyprctl", "-j", "clients"] else \
                json.dumps({"address": "0xdef", "at": [1, 2], "size": [3, 4]}) if argv[:3] == ["hyprctl", "-j", "activewindow"] else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        p = mock.patch.object(screen, "_run", fake)
        p.start(); self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state"),
                                         "HYPR_AGENT_SESSION": "s1"}, clear=True)
        e.start(); self.addCleanup(e.stop)

    def grim(self):
        return [c for c in self.calls if c[0] == "grim"][-1]

    def test_capture_window_geometry(self):
        path = screen.capture("window", address="0xabc")
        self.assertEqual(self.grim()[:3], ["grim", "-g", "10,20 300x200"])
        self.assertEqual(self.grim()[3], path)

    def test_capture_active_window_by_default(self):
        screen.capture()
        self.assertEqual(self.grim()[:3], ["grim", "-g", "1,2 3x4"])

    def test_capture_output_and_region(self):
        screen.capture("output", output="eDP-1")
        self.assertEqual(self.grim()[:3], ["grim", "-o", "eDP-1"])
        screen.capture("region", region="0,0 640x480")
        self.assertEqual(self.grim()[:3], ["grim", "-g", "0,0 640x480"])
        self.assertIn("refused", screen.capture("region", region="0,0 640x480; rm"))

    def test_capture_path_in_session(self):
        path = screen.capture("window", address="0xabc")
        self.assertTrue(path.startswith(str(self.root / "state/atomic-hyprland/agent/s1/screens/")))
        self.assertTrue(path.endswith(".png"))


if __name__ == "__main__":
    unittest.main()
