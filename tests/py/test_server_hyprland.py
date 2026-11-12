import subprocess
import unittest
from pathlib import Path
from unittest import mock

from atomic_agent.registry import load_registry
from atomic_agent.servers import hyprland, notify

REPO = Path(__file__).resolve().parents[2]


class HyprlandTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def fake(argv):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "ok\n", "")
        for mod in (hyprland, notify):
            p = mock.patch.object(mod, "_run", fake)
            p.start(); self.addCleanup(p.stop)

    def test_lua_str_escapes(self):
        self.assertEqual(hyprland.lua_str('a"b\nc'), '"a\\"b\\nc"')
        self.assertEqual(hyprland.lua_str("back\\slash"), '"back\\\\slash"')

    def test_launch_wraps_uwsm_app(self):
        self.assertEqual(hyprland.dispatch_expr("launch", command="pavucontrol"),
                         'hl.dsp.exec_cmd("uwsm-app -- pavucontrol")')

    def test_dispatch_expr_every_change_tool(self):
        args = {"focus_window": {"address": "0xabc"},
                "move_window_to_workspace": {"address": "0xabc", "workspace": 3},
                "resize_window": {"address": "0xabc", "width": 800, "height": 600},
                "close_window": {"address": "0xabc"},
                "switch_workspace": {"workspace": "special:magic"},
                "launch": {"command": "nautilus"},
                "reload_config": {}}
        self.assertEqual(set(args), set(hyprland.CHANGE_TOOLS))
        for tool, kw in args.items():
            expr = hyprland.dispatch_expr(tool, **kw)
            self.assertTrue(expr.startswith("hl.dsp."), (tool, expr))
        self.assertIn('window = "address:0xabc"', hyprland.dispatch_expr("close_window", address="0xabc"))

    def test_bad_arguments_refused(self):
        for tool, kw in (("close_window", {"address": '0x1"); os.exit(--'}),
                         ("switch_workspace", {"workspace": 'x" }) hl.dsp.exit() --'}),
                         ("resize_window", {"address": "0x1", "width": -5, "height": 10})):
            with self.assertRaises(ValueError):
                hyprland.dispatch_expr(tool, **kw)

    def test_change_tool_runs_hyprctl_dispatch(self):
        hyprland.close_window("0xabc")
        self.assertEqual(self.calls[-1], ["hyprctl", "dispatch", 'hl.dsp.window.close({ window = "address:0xabc" })'])

    def test_reads_use_json(self):
        hyprland.list_windows()
        self.assertEqual(self.calls[-1], ["hyprctl", "-j", "clients"])
        hyprland.active_window()
        self.assertEqual(self.calls[-1], ["hyprctl", "-j", "activewindow"])

    def test_notify(self):
        notify.notify("Done", "Bar restarted", "low")
        self.assertEqual(self.calls[-1], ["notify-send", "-a", "hypr-agent", "-u", "low", "Done", "Bar restarted"])
        self.assertIn("refused", notify.notify("x", urgency="--evil"))

    def test_registry_files(self):
        reg = load_registry([REPO / "files/usr/share/atomic-hyprland/mcp.d"])
        self.assertEqual(sorted(reg["hyprland"].read_only_tools), sorted(hyprland.READ_TOOLS))
        self.assertEqual(set(reg["hyprland"].tool_notes), set(hyprland.CHANGE_TOOLS))
        self.assertEqual(reg["screen"].read_only_tools, [])
        self.assertIn("capture", reg["screen"].tool_notes)
        self.assertEqual(reg["notify"].read_only_tools, [])


if __name__ == "__main__":
    unittest.main()
