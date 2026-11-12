import os
import unittest
from pathlib import Path
from unittest import mock

from atomic_agent import paths


class PathsTest(unittest.TestCase):
    def test_session_dir_under_state(self):
        with mock.patch.dict(os.environ, {"HOME": "/h", "XDG_STATE_HOME": "/s"}, clear=True):
            self.assertEqual(paths.session_dir("abc"), Path("/s/atomic-hyprland/agent/abc"))

    def test_defaults_without_xdg(self):
        with mock.patch.dict(os.environ, {"HOME": "/h"}, clear=True):
            self.assertEqual(paths.rules_file(), Path("/h/.config/atomic-hyprland/agent/permissions.json"))
            self.assertEqual(paths.state_dir(), Path("/h/.local/state/atomic-hyprland/agent"))
            self.assertEqual(paths.managed_file(), Path("/h/.local/state/atomic-hyprland/mcp-managed.json"))

    def test_runtime_and_pending(self):
        with mock.patch.dict(os.environ, {"HOME": "/h", "XDG_RUNTIME_DIR": "/run/user/7"}, clear=True):
            self.assertEqual(paths.runtime_dir(), Path("/run/user/7/hypr-agent"))
            self.assertEqual(paths.pending_dir(), Path("/run/user/7/hypr-agent/pending"))

    def test_registry_dirs_order(self):
        with mock.patch.dict(os.environ, {"HOME": "/h"}, clear=True):
            self.assertEqual(paths.registry_dirs(), [
                Path("/usr/share/atomic-hyprland/mcp.d"),
                Path("/etc/atomic-hyprland/mcp.d"),
                Path("/h/.config/atomic-hyprland/mcp.d"),
            ])
        env = {"HOME": "/h", "ATOMIC_AGENT_SHARE": "/x", "ATOMIC_AGENT_ETC": "/y", "XDG_CONFIG_HOME": "/c"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(paths.registry_dirs(), [Path("/x"), Path("/y"), Path("/c/atomic-hyprland/mcp.d")])


if __name__ == "__main__":
    unittest.main()
