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
        self.assertEqual(s["hooks"]["PostToolUse"][0]["hooks"][0]["command"], "hypr-agent hook post-tool-use")

    def test_build_settings_includes_user_rules(self):
        rules = write_json(self.root / "rules.json", '{"permissions": {"allow": ["Bash(make)"]}}')
        s = agent.build_settings(BASE, rules, registry())
        self.assertIn("Bash(make)", s["permissions"]["allow"])

    def test_ask_settings_ignore_always_rules(self):
        # I4: ask mode stays read-only even after the user saved "always allow" rules.
        rules = write_json(self.root / "rules.json", '{"permissions": {"allow": ["Bash(make)"]}}')
        s = agent.build_settings(BASE, rules, registry(), include_rules=False)
        self.assertNotIn("Bash(make)", s["permissions"]["allow"])
        self.assertIn("mcp__system__journal", s["permissions"]["allow"])

    def test_build_settings_drops_malformed_rules(self):
        # A non-string rule would make Claude Code ignore the whole settings file (hooks, denies).
        rules = write_json(self.root / "rules.json", '{"permissions": {"allow": ["Bash(make)", 5, {"x": 1}, null]}}')
        allow = agent.build_settings(BASE, rules, registry())["permissions"]["allow"]
        self.assertTrue(all(isinstance(r, str) for r in allow))
        self.assertIn("Bash(make)", allow)
        bad = write_json(self.root / "bad.json", '{"permissions": {"allow": "Bash(make)"}}')
        allow = agent.build_settings(BASE, bad, registry())["permissions"]["allow"]
        self.assertTrue(all(isinstance(r, str) for r in allow))

    def test_base_settings_no_free_network(self):
        # Reading is free, sending is not: a prompt injection must not be able to Read a
        # secret and WebFetch it out without an approval card.
        allow = BASE["permissions"]["allow"]
        self.assertNotIn("WebFetch", allow)
        self.assertNotIn("WebSearch", allow)
        deny = BASE["permissions"]["deny"]
        for rule in ("Read(~/.ssh/**)", "Read(~/.gnupg/**)", "Read(~/.claude/.credentials.json)",
                     "Read(~/.local/share/keyrings/**)", "Read(~/.config/gh/**)", "Read(~/.var/app/**)",
                     "Read(~/.aws/**)", "Read(~/.azure/**)", "Read(~/.kube/**)"):
            self.assertIn(rule, deny)

    def test_base_settings_guard_the_agent(self):
        deny = BASE["permissions"]["deny"]
        for rule in ("Bash(sudo:*)", "Bash(pkexec:*)", "Bash(su:*)", "Bash(run0:*)", "Bash(bootc switch:*)",
                     "Edit(~/.config/atomic-hyprland/agent/**)", "Edit(~/.config/atomic-hyprland/mcp.d/**)",
                     # session folders hold the undo manifest and copies: tampering would turn Undo into a write
                     "Edit(~/.local/state/atomic-hyprland/**)"):
            self.assertIn(rule, deny)
        self.assertEqual(BASE["permissions"]["disableBypassPermissionsMode"], "disable")
        self.assertIn("Edit(//etc/**)", deny)

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
        # No setting sources at all: a repo's .claude/settings.json (hooks, allow rules)
        # must never reach the agent. The terminal folder is added as a directory.
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--add-dir") + 1], "/h/app")
        self.assertNotIn("--permission-prompt-tool", argv)
        prompt = argv[-1]
        self.assertIn("/s/ask.png", prompt)
        self.assertIn("boom", prompt)
        self.assertIn("/h/app", prompt)
        self.assertTrue(prompt.startswith("why?"))


class FixStopUndoTest(unittest.TestCase):
    def setUp(self):
        import io, subprocess, threading
        self.io, self.subprocess, self.threading = io, subprocess, threading
        self.root = tmpdir(self)
        env = {"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state"),
               "XDG_CONFIG_HOME": str(self.root / "cfg"), "XDG_RUNTIME_DIR": str(self.root / "run"),
               "ATOMIC_AGENT_SHARE": str(REPO / "files/usr/share/atomic-hyprland/mcp.d"),
               "ATOMIC_AGENT_ETC": str(self.root / "etc"), "PATH": "/usr/bin:/bin"}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start(); self.addCleanup(p.stop)
        d = mock.patch.object(agent, "SHARE", REPO / "files/usr/share/atomic-hyprland/agent")
        d.start(); self.addCleanup(d.stop)
        self.calls = []

    def fake_run(self, argv, **kw):
        self.calls.append(argv)
        return self.subprocess.CompletedProcess(argv, 0, "", "")

    def test_fix_argv_uses_prompt_tool(self):
        argv = agent.fix_argv("s1", Path("/s/settings.json"), Path("/s/mcp.json"), Path("/s/prompt.md"))
        self.assertEqual(argv[:2], ["claude", "-p"])
        self.assertEqual(argv[argv.index("--resume") + 1], "s1")
        self.assertEqual(argv[argv.index("--permission-prompt-tool") + 1], "mcp__approvals__prompt")
        self.assertNotIn("--permission-prompts", argv)
        self.assertIn("Edit/Write", argv[-1])

    def test_agent_argv_ignores_user_settings(self):
        write_json(self.root / ".claude/settings.json",
                   '{"permissions": {"allow": ["Bash(*)"], "defaultMode": "bypassPermissions"}}')
        settings_file, mcp_file, prompt_file = agent.prepare_session("s1")
        text = settings_file.read_text()
        self.assertNotIn("Bash(*)", text)
        self.assertNotIn("bypassPermissions", text)
        for argv in (agent.fix_argv("s1", settings_file, mcp_file, prompt_file),
                     agent.chat_argv("s1", settings_file, mcp_file, prompt_file),
                     agent.ask_argv("s1", "q", Context(None, None, None), settings_file, mcp_file, prompt_file)):
            self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
            self.assertIn("--strict-mcp-config", argv)
            self.assertNotIn("bypassPermissions", argv)

    def test_chat_is_interactive(self):
        argv = agent.chat_argv("s1", Path("/s/a"), Path("/s/b"), Path("/s/c"))
        self.assertEqual(argv[:3], ["claude", "--resume", "s1"])
        self.assertNotIn("-p", argv)

    def test_stop_denies_pending(self):
        from atomic_agent import ui
        from atomic_agent.policy import Card
        pid = ui.new_pending(Card("t", "d", "u", None), "s1")
        result = {}
        t = self.threading.Thread(target=lambda: result.update(answer=ui.wait_answer(pid, timeout=5, poll=0.02)))
        t.start()
        agent.stop_all(run=self.fake_run)
        t.join(1)
        self.assertFalse(t.is_alive())
        self.assertEqual(result["answer"], "deny")
        self.assertIn(["systemctl", "--user", "stop", "hypr-agent-*.service"], self.calls)

    def test_stop_cleans_orphan_pending(self):
        # C2: when stop kills the approvals server, nothing is left waiting forever.
        from atomic_agent import paths, ui
        from atomic_agent.policy import Card
        pid = ui.new_pending(Card("t", "d", "u", None), "s1")
        ui._record_notification(pid, "9")
        with mock.patch("time.sleep"):
            agent.stop_all(run=self.fake_run)
        self.assertEqual(list(paths.pending_dir().iterdir()), [])
        self.assertIn(["makoctl", "dismiss", "-n", "9"], self.calls)

    def test_finalize_screenshot(self):
        # I5: a removed (or cancelled) screenshot is deleted, not left where the agent can Read it.
        shot = self.root / "run/ask.png"
        shot.parent.mkdir(parents=True)
        shot.write_bytes(b"png")
        ctx = agent.finalize_screenshot(Context(None, None, None), shot, self.root / "sess")
        self.assertIsNone(ctx.screenshot)
        self.assertFalse(shot.exists())
        shot.write_bytes(b"png")
        ctx = agent.finalize_screenshot(Context(shot, None, None), shot, self.root / "sess")
        self.assertEqual(ctx.screenshot, self.root / "sess/screens/ask.png")
        self.assertTrue(ctx.screenshot.exists())
        self.assertFalse(shot.exists())

    def test_answer_card_is_plain_with_full_answer_view(self):
        answer = "**Fine.** Shows:\n```\nok\n```\n" + "more " * 200
        body, choices, views = agent.answer_card(answer)
        self.assertTrue(body.startswith("Fine. Shows:\n  ok"))
        self.assertTrue(body.endswith("Click for: full answer · Fix it · chat"))
        self.assertEqual([k for k, _ in choices], ["read", "fix", "chat", "dismiss"])
        self.assertEqual(views, {"read": answer})

    def test_finalize_screenshot_across_filesystems(self):
        # The screenshot waits in $XDG_RUNTIME_DIR (tmpfs) and is kept under ~/.local/state
        # (btrfs on real installs): a rename across them fails with EXDEV.
        import errno
        shot = self.root / "run/ask.png"
        shot.parent.mkdir(parents=True)
        shot.write_bytes(b"png")

        def exdev(*a, **k):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        with mock.patch("os.replace", exdev), mock.patch("os.rename", exdev):
            ctx = agent.finalize_screenshot(Context(shot, None, None), shot, self.root / "sess")
        self.assertEqual(ctx.screenshot.read_bytes(), b"png")
        self.assertFalse(shot.exists())

    def test_main_reports_a_crash_as_a_notification(self):
        # Super+A runs from a keybind with no terminal: a crash must reach the screen.
        calls = []
        with mock.patch.dict(agent.COMMANDS, {"ask": mock.Mock(side_effect=RuntimeError("boom"))}), \
                mock.patch.object(agent.subprocess, "run", lambda argv, **k: calls.append(argv)), \
                mock.patch("sys.stderr", self.io.StringIO()):
            self.assertEqual(agent.main(["ask"]), 1)
        self.assertEqual(calls[0][:4], ["notify-send", "-a", "hypr-agent", "-u"])
        self.assertIn("boom", calls[0][-1])

    def test_main_leaves_hook_errors_to_the_hook(self):
        # Hooks fail closed with their own exit codes; main must not turn them into 1.
        with mock.patch.dict(agent.COMMANDS, {"hook": mock.Mock(side_effect=RuntimeError("boom"))}):
            with self.assertRaises(RuntimeError):
                agent.main(["hook", "pre-tool-use"])

    def test_hook_cli_bad_stdin_blocks(self):
        with mock.patch("sys.stdin", self.io.StringIO("not json")), mock.patch("sys.stderr", self.io.StringIO()):
            self.assertEqual(agent.dispatch(["hook", "pre-tool-use"]), 2)

    def test_stop_kills_ask_and_dismisses_cards(self):
        from atomic_agent import paths, ui
        from atomic_agent.policy import Card
        pid = ui.new_pending(Card("t", "d", "u", None), "s1")
        data = json.loads((paths.pending_dir() / f"{pid}.json").read_text())
        data["notification"] = "42"
        (paths.pending_dir() / f"{pid}.json").write_text(json.dumps(data))
        (paths.runtime_dir() / "ask.pid").write_text("999999")
        with mock.patch("os.kill") as kill:
            agent.stop_all(run=self.fake_run)
        kill.assert_called()
        self.assertIn(["makoctl", "dismiss", "-n", "42"], self.calls)
        self.assertIn(["pkill", "-TERM", "-P", "999999"], self.calls)

    def test_start_fix_unit_name(self):
        unit = agent.start_fix("0123456789ab-cdef", run=self.fake_run)
        self.assertEqual(unit, "hypr-agent-01234567")
        argv = self.calls[-1]
        self.assertEqual(argv[:4], ["systemd-run", "--user", "--unit=hypr-agent-01234567", "--collect"])
        self.assertEqual(argv[-4:], ["--", "hypr-agent", "run-fix", "0123456789ab-cdef"])

    def test_undo_session_routes_etc_to_helper(self):
        from atomic_agent import paths
        sdir = paths.session_dir("s1")
        (sdir / "files").mkdir(parents=True)
        (sdir / "files/0").write_text("orig")
        (sdir / "manifest.jsonl").write_text(
            '{"path": "/etc/hosts", "existed": true, "copy": "files/0"}\n'
            '{"event": "applied", "path": "/etc/hosts"}\n'
            '{"path": "/etc/new.conf", "existed": false, "copy": null}\n'
            '{"event": "applied", "path": "/etc/new.conf"}\n')
        restored = agent.undo_session("s1", run=self.fake_run)
        self.assertEqual(restored, ["/etc/new.conf", "/etc/hosts"])
        helper = "/usr/libexec/atomic-hyprland/agent-root"
        self.assertEqual(self.calls, [["pkexec", helper, "etc-restore", "/etc/new.conf", "-"],
                                      ["pkexec", helper, "etc-restore", "/etc/hosts", str(sdir / "files/0")]])

    def test_hook_cli_exit_code(self):
        f = self.root / "notes.txt"
        f.write_text("orig")
        ev = {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": str(f)}}
        with mock.patch("sys.stdin", self.io.StringIO(json.dumps(ev))):
            self.assertEqual(agent.dispatch(["hook", "pre-tool-use"]), 0)
        f.chmod(0)
        self.addCleanup(f.chmod, 0o600)
        ev["session_id"] = "s2"
        with mock.patch("sys.stdin", self.io.StringIO(json.dumps(ev))), mock.patch("sys.stderr", self.io.StringIO()):
            self.assertEqual(agent.dispatch(["hook", "pre-tool-use"]), 2 if not os.access(f, os.R_OK) else 0)

    def test_sessions_lists_changes(self):
        from atomic_agent import paths
        agent.save_meta("s1", mode="fix", cwd="/h")
        (paths.session_dir("s1") / "manifest.jsonl").write_text(
            '{"path": "/h/a", "existed": true, "copy": "files/0"}\n{"event": "applied", "path": "/h/a"}\n')
        with mock.patch("sys.stdout", self.io.StringIO()) as out:
            agent.dispatch(["sessions"])
        self.assertIn("s1", out.getvalue())
        self.assertIn("1 change", out.getvalue())


if __name__ == "__main__":
    unittest.main()
