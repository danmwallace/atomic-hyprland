import json
import os
import unittest
from pathlib import Path
from unittest import mock

from atomic_agent import agent
from atomic_agent.context import Context
from atomic_agent.registry import ServerDef
from helpers import tmpdir, write_json

REPO = Path(__file__).resolve().parents[2]
BASE = json.loads((REPO / "files/usr/share/atomic-hyprland/agent/settings.json").read_text())


def registry():
    return {"system": ServerDef(name="system", spec={"command": "x"}, read_only_tools=["journal"],
                                root_tools=["restart_unit"]),
            "web": ServerDef(name="web", spec={"type": "http", "url": "https://x.test"})}


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        p = mock.patch.dict(os.environ, {"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state"),
                                         "XDG_CONFIG_HOME": str(self.root / "cfg"), "PATH": "/usr/bin"}, clear=True)
        p.start(); self.addCleanup(p.stop)

    def test_build_settings_read_only_tools_allowed(self):
        s = agent.build_settings(BASE, self.root / "none.json", registry())
        allow = s["permissions"]["allow"]
        self.assertIn("mcp__system__journal", allow)
        self.assertNotIn("mcp__system__restart_unit", allow)
        self.assertIn("Read", allow)
        self.assertEqual(s["permissions"]["defaultMode"], "default")
        hook = s["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], "Edit|Write|MultiEdit|NotebookEdit")
        self.assertEqual(hook["hooks"][0]["command"], "hypr-agent hook pre-tool-use")

    def test_build_settings_includes_user_rules(self):
        rules = write_json(self.root / "rules.json", '{"permissions": {"allow": ["Bash(make)"]}}')
        s = agent.build_settings(BASE, rules, registry())
        self.assertIn("Bash(make)", s["permissions"]["allow"])

    def test_base_settings_guard_the_agent(self):
        deny = BASE["permissions"]["deny"]
        for rule in ("Bash(sudo:*)", "Bash(pkexec:*)", "Bash(su:*)", "Bash(run0:*)", "Bash(bootc switch:*)",
                     "Edit(~/.config/atomic-hyprland/agent/**)", "Edit(~/.config/atomic-hyprland/mcp.d/**)"):
            self.assertIn(rule, deny)
        self.assertEqual(BASE["permissions"]["disableBypassPermissionsMode"], "disable")

    def test_mcp_config(self):
        cfg = agent.mcp_config(registry())["mcpServers"]
        self.assertEqual(cfg["system"], {"type": "stdio", "command": "hypr-mcp", "args": ["run", "system"]})
        self.assertEqual(cfg["web"], {"type": "http", "url": "https://x.test"})
        self.assertEqual(cfg["approvals"]["args"], ["approvals"])

    def test_agent_env(self):
        env = agent.agent_env("s1")
        self.assertEqual(env["HYPR_AGENT_SESSION"], "s1")
        self.assertEqual(env["MCP_TOOL_TIMEOUT"], "660000")
        self.assertNotIn("CLAUDECODE", agent.agent_env("s1") if "CLAUDECODE" not in os.environ else {})

    def test_system_prompt_joins_claude_md(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude/CLAUDE.md").write_text("I like helix.")
        f = agent.system_prompt_file("s1", instructions=REPO / "files/usr/share/atomic-hyprland/agent/instructions.md")
        text = f.read_text()
        self.assertIn("Edit", text)
        self.assertTrue(text.rstrip().endswith("I like helix."))

    def test_ask_argv_read_only(self):
        ctx = Context(screenshot=Path("/s/ask.png"), clipboard="boom", cwd=Path("/h/app"))
        argv = agent.ask_argv("s1", "why?", ctx, Path("/s/settings.json"), Path("/s/mcp.json"), Path("/s/prompt.md"))
        self.assertEqual(argv[:2], ["claude", "-p"])
        for flag in ("--session-id", "--setting-sources", "--strict-mcp-config", "--append-system-prompt-file"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")
        self.assertNotIn("--permission-prompt-tool", argv)
        prompt = argv[-1]
        self.assertIn("/s/ask.png", prompt)
        self.assertIn("boom", prompt)
        self.assertIn("/h/app", prompt)
        self.assertTrue(prompt.startswith("why?"))


if __name__ == "__main__":
    unittest.main()
