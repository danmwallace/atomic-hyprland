# Agentic Desktop (piece 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Super+A asks a read-only Claude agent about what is on screen; "Fix it" lets it remediate in the background behind approval cards with stop and undo; desktop MCP servers and a drop-in MCP registry make the OS extensible.

**Architecture:** One Python package (`atomic_agent`) holds all logic as plain functions that are unit-tested on the host; thin entry points (`hypr-agent`, `hypr-mcp`, one MCP server per desktop area, a polkit-gated root helper) wire it to Claude Code, mako, wofi, hyprctl and systemd. Agent sessions run Claude Code headless with isolated settings, their own MCP config, a permission-prompt tool for approvals and a PreToolUse hook for undo snapshots.

**Tech Stack:** Python 3.14 (Fedora 44) with `python3-mcp` 1.26 (FastMCP, stdio); Claude Code 2.1.289 (`claude -p`); mako + `notify-send`; wofi dmenu; hyprctl (Hyprland 0.57 Lua dispatchers); systemd user units; polkit + pkexec; bash host tests.

**Spec:** `docs/superpowers/specs/2026-11-11-agentic-desktop-design.md`

## Global Constraints

- Nothing changes without asking: every state-changing action needs Allow unless a saved "always allow" rule covers it (spec, hard requirement 1).
- Never always-allowable: root actions, `git push`, PR creation, bootc upgrade/rollback, deleting files, any screenshot (decision 8).
- Ask mode is read-only: no approvals, nothing that changes state can run (spec 1).
- Approval not answered in 10 minutes = Deny (spec 2).
- The agent never gets general root: `sudo`, `pkexec` (except via the root helper tools), `su`, `run0` are denied in agent settings (spec 3a).
- Root helper ops only: unit start/stop/restart, `bootc upgrade` (stage only), `bootc rollback`, snapshot/write/restore a file under `/etc`; polkit `auth_admin_keep` (spec 3a).
- `bootc switch` is never offered to an agent (spec 4).
- `hypr-agent` sessions load their own settings, not `~/.claude/settings.json` permissions; CLAUDE.md and memory still load (decision 3).
- Ships nothing Dan-specific; no secrets in files (spec, hard requirement 4).
- Python dependencies from Fedora repos only; `python3-mcp` is the one new package (decision 6). Mention it in the commit body.
- Tools are named `hypr-*`; Python entry points use `#!/usr/bin/python3 -I` like the existing waybar helpers.
- Bind combos must not collide (`tests/test-binds.sh`); Hyprland dispatchers are Lua strings (`hyprctl dispatch 'hl.dsp....'`).
- Every task: test first, watch it fail, then implement; `just test`'s host-side suites stay green.

## Plan Decisions (made here, within what the spec leaves to the builder)

- **Undo snapshots come from a PreToolUse hook, not the approval tool.** An edit covered by an "always allow" rule never reaches the approval tool, so only a hook sees every Edit/Write. The hook (`hypr-agent hook pre-tool-use`) blocks the edit if the snapshot fails.
- **Approval and answer cards are a mako notification plus a one-key wofi menu.** mako draws no buttons. A left click on the card (its default action) or Super+Y opens the menu (Allow / Deny / Always allow: <rule> / Details). A right click dismisses, which counts as Deny. A buttons popup can come later.
- **`/etc` changes go through the system server's `write_etc_file` tool** (root helper). Claude's own Edit cannot write `/etc` as the user.
- **The agent's MCP set is explicit.** `--mcp-config` (registry servers plus approvals) with `--strict-mcp-config`, because `--setting-sources project,local` also drops the user-scope servers.
- **The image's source repo comes from one `ARG IMAGE_SOURCE`** that feeds both the OCI label and `/usr/share/atomic-hyprland/image-source`, so a fork edits it once.
- **Open chat uses terminal permission prompts** (interactive Claude Code), with the same isolated settings and the same snapshot hook. If Task 1 shows `--permission-prompt-tool` works interactively, use it instead and record the ruling.

## Review Focus

1. Dan's `~/.claude/settings.json` holds `"defaultMode": "bypassPermissions"` or `Bash(*)`: an agent session must still route changes to approval cards. (Task 11: `test_agent_argv_ignores_user_settings`)
2. Two approvals pending at once: Super+Y answers the oldest, the card click answers its own, and neither answer leaks to the other. (Task 6: `test_two_pending_answered_independently`)
3. Stop pressed while an approval is pending: the waiting approval returns Deny within a second and the unit stops. (Task 11: `test_stop_denies_pending`)
4. The agent creates a new file, then edits the same file twice: undo deletes the created file and restores the pre-session content of the edited one, not an intermediate version. (Task 5: `test_undo_created_file_removed`, `test_undo_restores_first_snapshot`)
5. Root helper given `/etc/../usr/bin/x`, a symlink under `/etc` pointing into `/usr`, or a session folder not owned by the calling user: refuse. (Task 7: `test_rejects_traversal`, `test_rejects_symlink_escape`, `test_rejects_foreign_session_dir`)

---

## File Structure

```
files/usr/lib/atomic-hyprland/python/atomic_agent/
  __init__.py
  paths.py        state/config/runtime locations
  registry.py     MCP drop-in registry: load, merge, readOnlyTools
  secrets.py      resolve keyring / systemd-creds env references
  mcp_sync.py     write registry into Claude Code (user scope) and Gemini CLI
  policy.py       read/change, always-allow rule, never-always, undo labels, card text
  snapshots.py    per-session snapshot manifest and undo
  ui.py           cards: pending approvals, notify-send, wofi menus
  context.py      Super+A capture: window geometry, terminal cwd, clipboard
  agent.py        claude argv/settings builders for ask, fix, chat
  prtarget.py     self-improvement PR target resolution
  servers/__init__.py
  servers/hyprland.py  servers/system.py  servers/screen.py
  servers/notify.py    servers/approvals.py
files/usr/bin/hypr-agent  files/usr/bin/hypr-mcp
files/usr/libexec/atomic-hyprland/agent-root          root helper (standalone)
files/usr/libexec/atomic-hyprland/mcp-server          runs atomic_agent.servers.<name>
files/usr/libexec/atomic-hyprland/waybar/agent        bar indicator
files/usr/share/polkit-1/actions/org.atomic-hyprland.agent.policy
files/usr/share/atomic-hyprland/mcp.d/{hyprland,system,screen,notify}.json
files/usr/share/atomic-hyprland/agent/{settings.json,instructions.md}
files/usr/lib/systemd/user/hypr-mcp-sync.{service,path}
tests/py/test_*.py   tests/test-agent.sh   tests/mcp-smoke.py
```

Entry points add the package to `sys.path` from `ATOMIC_AGENT_PYLIB` (default `/usr/lib/atomic-hyprland/python`). `-I` ignores `PYTHONPATH` but not `os.environ`. Each server module keeps its logic in plain functions and imports `mcp` only inside `main()`, so host tests run without `python3-mcp` installed.

---

### Task 1: Verify the assumptions the design rests on

No product code. The output is a notes file the later tasks read.

**Files:**
- Create: `docs/superpowers/notes/2026-11-11-agentic-desktop-verify.md`

**Interfaces:**
- Produces: findings A–G below, each "confirmed" or "differs: <what>, ruling: <what we do instead>".

- [ ] **Step 1: Claude Code flags at the pinned version.** Run `podman run --rm ghcr.io/danmwallace/atomic-hyprland:44 claude --help` and record whether `--permission-prompt-tool`, `--permission-prompts`, `--setting-sources`, `--settings`, `--mcp-config`, `--strict-mcp-config`, `--session-id`, `--resume` and `--append-system-prompt-file` exist.
- [ ] **Step 2: Permission-prompt tool contract (finding A).** With a throwaway stdio MCP server exposing `prompt(tool_name: str, input: dict) -> str` that logs its arguments and returns `{"behavior":"deny","message":"test"}`, run `claude -p --permission-prompt-tool mcp__t__prompt --mcp-config <cfg> --strict-mcp-config "create /tmp/x.txt containing hi"`. Record the exact argument names received, and the allow shape (`{"behavior":"allow","updatedInput":{...}}`). Repeat interactively (`claude` without `-p`) and record whether the tool is consulted.
- [ ] **Step 3: Settings isolation (finding B).** With `HOME` pointing at a temp folder whose `~/.claude/settings.json` has `{"permissions":{"allow":["Write"]}}` and whose `~/.claude/CLAUDE.md` says "the codeword is PLUM", plus Dan's credentials copied in: run with `--setting-sources project,local`. Record whether Write still prompts (it must), whether the model knows PLUM, and whether login works. If CLAUDE.md is dropped, the ruling is to pass `--append-system-prompt-file ~/.claude/CLAUDE.md`.
- [ ] **Step 4: Hooks from `--settings` in `-p` mode (finding C).** A PreToolUse hook on `Edit|Write` that appends stdin to a log. Record the JSON fields (`session_id`, `tool_name`, `tool_input.file_path`), and confirm that exit code 2 blocks the tool.
- [ ] **Step 5: `python3-mcp` (finding D).** In `podman run --rm -it registry.fedoraproject.org/fedora:44`, run `dnf -y install python3-mcp` and a FastMCP stdio server with one tool listed through `mcp.client.stdio`. Record the import paths that work (`from mcp.server.fastmcp import FastMCP`) and whether tool annotations (`readOnlyHint`) are supported.
- [ ] **Step 6: polkit from a user unit (finding E).** With Dan present at the T430 or the Alienware, run `systemd-run --user --wait pkexec /usr/bin/true` and record whether the hyprpolkitagent dialog appears. If Dan is not available, record "open" and continue; Task 7's smoke step re-checks it.
- [ ] **Step 7: Gemini CLI MCP format (finding F)** from the Gemini CLI docs: the `mcpServers` keys for stdio (`command`, `args`, `env`) and HTTP (`httpUrl` / `url`).
- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/notes/2026-11-11-agentic-desktop-verify.md
git commit -m "docs(notes): verify Claude Code, python3-mcp and polkit assumptions"
```

---

### Task 2: Package scaffold, paths, test runner, `python3-mcp`

**Files:**
- Create: `files/usr/lib/atomic-hyprland/python/atomic_agent/__init__.py`, `paths.py`, `servers/__init__.py`; `tests/py/test_paths.py`; `tests/test-agent.sh`
- Modify: `build/packages.txt` (add `python3-mcp` after `python3-pip`), `justfile` (`bash tests/test-agent.sh` after `test-terminal.sh`), `tests/image-smoke.sh`, `tests/test-skel-includes.sh`

**Interfaces:**
- Produces, in `paths.py` (all return `pathlib.Path`, honouring `XDG_STATE_HOME`, `XDG_CONFIG_HOME`, `XDG_RUNTIME_DIR` and `HOME`):
  `state_dir()` = `$XDG_STATE_HOME/atomic-hyprland/agent`; `session_dir(sid: str)` = `state_dir()/sid`; `runtime_dir()` = `$XDG_RUNTIME_DIR/hypr-agent`; `pending_dir()` = `runtime_dir()/pending`; `rules_file()` = `$XDG_CONFIG_HOME/atomic-hyprland/agent/permissions.json`; `registry_dirs()` = `[/usr/share/atomic-hyprland/mcp.d, /etc/atomic-hyprland/mcp.d, $XDG_CONFIG_HOME/atomic-hyprland/mcp.d]` (the first two overridable with `ATOMIC_AGENT_SHARE` / `ATOMIC_AGENT_ETC` for tests); `managed_file()` = `$XDG_STATE_HOME/atomic-hyprland/mcp-managed.json`.
- `tests/test-agent.sh` runs `python3 -m unittest discover -s tests/py -t . -v` with `ATOMIC_AGENT_PYLIB` and `PYTHONPATH` set to the package root. Later tasks add their shell checks to this script.

- [ ] **Step 1: Write failing tests.** `tests/py/test_paths.py`: `test_session_dir_under_state` (with `XDG_STATE_HOME=/s`, `session_dir("abc") == Path("/s/atomic-hyprland/agent/abc")`); `test_defaults_without_xdg` (with only `HOME=/h`, `rules_file() == Path("/h/.config/atomic-hyprland/agent/permissions.json")`); `test_registry_dirs_order`. Shell checks in `test-skel-includes.sh`: `check grep -qx python3-mcp build/packages.txt`. In `image-smoke.sh`: `check python3 -c 'from mcp.server.fastmcp import FastMCP'` (use the import path from Task 1, finding D).
- [ ] **Step 2: Run** `bash tests/test-agent.sh` and `bash tests/test-skel-includes.sh`. Expected: FAIL (`No module named atomic_agent`, python3-mcp missing).
- [ ] **Step 3: Implement** `paths.py` and the runner; add the package and the justfile line.
- [ ] **Step 4: Run both again.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): atomic_agent package scaffold and test runner`. The body names the new dependency: python3-mcp (Fedora).

---

### Task 3: MCP registry and secret references

**Files:**
- Create: `atomic_agent/registry.py`, `atomic_agent/secrets.py`, `tests/py/test_registry.py`, `tests/py/test_secrets.py`

**Interfaces:**
- Produces:
  - `@dataclass ServerDef(name: str, spec: dict, read_only_tools: list[str], tool_notes: dict[str, str], root_tools: list[str], source: Path)`. `spec` holds the MCP keys (`command`, `args`, `env` or `type`, `url`, `headers`). The registry-only keys are `readOnlyTools`, `toolNotes` (tool → the undo note shown on its card) and `rootTools` (tools that run as root, never always-allowable); none of them leak into `spec`.
  - `load_registry(dirs: list[Path]) -> dict[str, ServerDef]`. The name is the file stem. A later dir replaces a same-named file. `"disabled": true` removes the server. Invalid JSON, or a file with neither `command` nor `url`, is skipped with a warning to stderr.
  - `secrets.resolve_env(env: dict) -> dict[str, str]`. A plain string passes through; `{"keyring": {"service": S, "account": A}}` → `secret-tool lookup service S account A`; `{"credential": N}` → `systemd-creds --user decrypt $XDG_CONFIG_HOME/atomic-hyprland/credentials/N.cred -`. An empty or failed lookup raises `SecretError(name)`.

- [ ] **Step 1: Write failing tests:**
  - `test_later_dir_overrides`: share `a.json` has command `x`, user `a.json` has command `y` → `spec["command"] == "y"`.
  - `test_disabled_removes`: the user file `{"disabled": true}` drops `a`.
  - `test_read_only_tools`: the field round-trips; it defaults to `[]`.
  - `test_tool_notes_and_root_tools`: both round-trip (defaults `{}` and `[]`) and stay out of `spec`.
  - `test_invalid_file_skipped`.
  - `test_url_server`.
  - `test_plain_env_passthrough`.
  - `test_keyring_lookup`: a stub `secret-tool` on PATH prints `tok`, and the exact argv is asserted.
  - `test_missing_secret_raises`.
- [ ] **Step 2: Run** `bash tests/test-agent.sh`. Expected: FAIL (`ImportError`).
- [ ] **Step 3: Implement** both modules.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): MCP drop-in registry and secret references`.

---

### Task 4: `hypr-mcp` (sync and run) and its user units

**Files:**
- Create: `atomic_agent/mcp_sync.py`, `files/usr/bin/hypr-mcp`, `files/usr/lib/systemd/user/hypr-mcp-sync.service`, `hypr-mcp-sync.path`, `tests/py/test_mcp_sync.py`
- Modify: `build/40-finalize.sh` (`systemctl --global enable hypr-mcp-sync.service hypr-mcp-sync.path`), `tests/test-agent.sh`, `tests/image-smoke.sh`

**Interfaces:**
- Consumes: `load_registry`, `resolve_env`, `paths.registry_dirs()`, `paths.managed_file()`.
- Produces:
  - `client_entry(d: ServerDef) -> dict`: stdio becomes `{"type":"stdio","command":"hypr-mcp","args":["run", d.name]}`; URL servers pass through unchanged.
  - `sync_claude(defs, managed: set[str], run=subprocess.run) -> set[str]`: uses `claude mcp get <n>` to test existence, `claude mcp remove --scope user <n>` and `claude mcp add-json --scope user <n> <json>`. It never touches a name it does not manage that already exists (warns instead). It removes managed names no longer in `defs`, and returns the new managed set.
  - `sync_gemini(defs, managed, settings: Path) -> set[str]`: only when `shutil.which("gemini")` or `settings.parent` exists. It edits `mcpServers` in place, preserves other keys, writes atomically, and uses the key names from Task 1, finding F.
  - CLI: `hypr-mcp sync`; `hypr-mcp run <name>` (resolves env, then `os.execvpe` the server command); `hypr-mcp list` (name, source, read-only tools).
- `hypr-mcp-sync.service`: `Type=oneshot`, `ExecStart=/usr/bin/hypr-mcp sync`, `WantedBy=default.target`. The `.path` unit watches `PathChanged=` on `/etc/atomic-hyprland/mcp.d` and `%h/.config/atomic-hyprland/mcp.d` (with `MakeDirectory=yes` for the latter), and has `WantedBy=default.target`.

- [ ] **Step 1: Write failing tests**, with a recording `run` stub:
  - `test_adds_new_server`: the argv includes `add-json --scope user hyprland` and the JSON names `hypr-mcp run hyprland`.
  - `test_updates_managed`: remove, then add.
  - `test_skips_user_owned`: `get` succeeds, the name is not managed → no remove/add, plus a warning.
  - `test_removes_dropped`.
  - `test_gemini_preserves_other_keys`.
  - `test_gemini_skipped_when_absent`.
  - `test_run_execs_with_resolved_env`: `os.execvpe` patched.

  Shell checks: both unit files exist, `40-finalize.sh` enables them, and `hypr-mcp` is executable.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. Image-smoke: `check test -L /etc/systemd/user/default.target.wants/hypr-mcp-sync.path`.
- [ ] **Step 5: Commit** `feat(agent): hypr-mcp syncs the registry into Claude Code and Gemini CLI`.

---

### Task 5: Policy, snapshots, undo and the snapshot hook

**Files:**
- Create: `atomic_agent/policy.py`, `atomic_agent/snapshots.py`, `tests/py/test_policy.py`, `tests/py/test_snapshots.py`

**Interfaces:**
- Produces, in `policy.py`:
  - `EDIT_TOOLS = {"Edit","Write","MultiEdit","NotebookEdit"}`
  - `always_rule(tool_name: str, tool_input: dict) -> str | None`. MCP tool → its full name (`mcp__hyprland__focus_window`). Bash → `Bash(<command>:*)`. An edit tool → `Edit(<file_path>)` or `Write(<file_path>)`. Returns `None` when `never_always()` is true.
  - `never_always(tool_name, tool_input, root_tools: set[str]) -> bool`. True for the tools in `root_tools`; for `mcp__screen__*`; for Bash whose command starts (after `env`/whitespace) with `git push`, `gh pr create`, `sudo`, `pkexec`, `su`, `run0`, `bootc`, `rm`, `rmdir`, `shred`, `unlink`, or `find … -delete`; and for Write with empty content over an existing file.
  - `undo_note(tool_name, tool_input, tool_notes: dict[str,str]) -> str`. Edit tools → `"Undo restores the file."`; Bash → `"Can't be undone automatically."`; an MCP tool → `tool_notes.get(name, "Can't be undone automatically.")`.
  - `@dataclass Card(title: str, detail: str, undo: str, rule: str | None)`
  - `card_for(tool_name, tool_input, tool_notes, root_tools) -> Card`. `detail` is the literal command, a unified diff for Edit (`old_string`→`new_string`), the content head (40 lines) for Write, or pretty JSON for MCP.
- Produces, in `snapshots.py` (manifest `session_dir/manifest.jsonl`, copies in `session_dir/files/<n>`):
  - `snapshot(sdir: Path, path: Path) -> None`: records `{"path", "existed": bool, "copy": "files/<n>" | None}`. A path already in the manifest is not snapshotted again.
  - `undo(sdir: Path, restore_etc=callable) -> list[str]`: reverse order. An existing-file entry is copied back; a created-file entry is deleted. `/etc` paths go to `restore_etc(path, copy)`. Returns the restored paths and marks the manifest `undone`.
  - `hook_pre_tool_use(event: dict, snapshot_etc=callable) -> int`: for `EDIT_TOOLS` it snapshots `tool_input["file_path"]` into `session_dir(event["session_id"])` and returns 0; it returns 2 when snapshotting fails; it returns 0 for every other tool.

- [ ] **Step 1: Write failing tests:**
  - `test_rule_bash_prefix`: `Bash` `{"command":"systemctl --user restart waybar"}` gives `Bash(systemctl --user restart waybar:*)`.
  - `test_rule_mcp_tool`.
  - `test_never_always_git_push`.
  - `test_never_always_sudo_with_env_prefix`.
  - `test_never_always_screen`.
  - `test_never_always_rm`.
  - `test_undo_note_bash`.
  - `test_card_edit_has_diff`.
  - `test_snapshot_once_per_path`.
  - `test_undo_created_file_removed`.
  - `test_undo_restores_first_snapshot`: write v1, snapshot, write v2, snapshot (no-op), write v3, undo gives v1.
  - `test_undo_reverse_order`.
  - `test_hook_blocks_when_snapshot_fails`: an unreadable file gives 2.
  - `test_hook_ignores_bash`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): approval policy, undo snapshots and the snapshot hook`.

---

### Task 6: Cards, pending approvals and the approvals server

**Files:**
- Create: `atomic_agent/ui.py`, `atomic_agent/servers/approvals.py`, `files/usr/libexec/atomic-hyprland/mcp-server`, `tests/py/test_ui.py`, `tests/py/test_approvals.py`

**Interfaces:**
- Consumes: `policy.card_for`, `policy.always_rule`, `paths.pending_dir()`, `paths.rules_file()`.
- Produces, in `ui.py`:
  - `new_pending(card: Card, session: str) -> str`: writes `pending/<id>.json`, where the id is a time-ordered `"%013d-%s" % (ms, uuid4().hex[:6])`, and returns the id.
  - `answer(pid: str, choice: str) -> None`: writes `pending/<id>.answer`. `choice` is one of `allow`, `deny`, `always`.
  - `wait_answer(pid, timeout: float = 600.0, poll: float = 0.25) -> str`: returns the answer. Timeout, or the pending file disappearing, gives `"deny"`. It cleans up both files.
  - `oldest_pending() -> str | None`.
  - `show_card(pid, card, notify=…)`: background `notify-send -u critical -a hypr-agent -A default=Review --wait <title> <body>`. Output `default` runs `review(pid)`. A dismissal without an action calls `answer(pid, "deny")`.
  - `review(pid, menu=…) -> None`: wofi dmenu (`wofi --dmenu --prompt <title> --lines 6`) with the lines `Allow`, `Deny`, `Always allow: <rule>` (omitted when `rule is None`) and `Details…`. Details opens `hypr-terminal -e less <detail-file>`, then the menu again. Escape changes nothing.
  - `choose(title: str, body: str, choices: list[tuple[str,str]], menu=…, notify=…) -> str | None`: the generic card plus menu used for the ask answer card (`fix`, `chat`, `dismiss`).
- Produces, in `servers/approvals.py`:
  - `decide(tool_name, tool_input, ask=callable) -> dict`. The session comes from `HYPR_AGENT_SESSION`, the tool notes and root tools from `load_registry(registry_dirs())`. It builds the card, creates the pending entry, shows it and waits. It returns `{"behavior":"allow","updatedInput":tool_input}` or `{"behavior":"deny","message":"Denied by the user"}`. `always` appends `card.rule` to the `permissions.allow` list in `rules_file()` (creating `{"permissions":{"allow":[]}}`), then allows. The argument names and the reply shape follow Task 1, finding A.
  - `main()`: FastMCP server `approvals` with one tool `prompt`.
- `mcp-server <name>`: runs `atomic_agent.servers.<name>.main()` (the shared launcher every registry file points at).

- [ ] **Step 1: Write failing tests**, with stub `notify-send` and `wofi` scripts on PATH that print a scripted choice:
  - `test_wait_times_out_to_deny`: timeout 0.2.
  - `test_pending_removed_means_deny`.
  - `test_two_pending_answered_independently`: two ids; answer the second `allow`, the first stays waiting; `oldest_pending()` is the first.
  - `test_review_allow`.
  - `test_review_escape_no_answer`.
  - `test_always_hidden_when_no_rule`.
  - `test_decide_always_writes_rule`: the rules file afterwards contains `Bash(systemctl --user restart waybar:*)`.
  - `test_decide_deny_shape`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. Add `tests/mcp-smoke.py <server> <tool>...`, which lists tools over stdio and exits 1 if one is missing. Image-smoke: `check python3 /tests/mcp-smoke.py approvals prompt`.
- [ ] **Step 5: Commit** `feat(agent): approval cards and the permission-prompt server`.

---

### Task 7: Root helper and polkit policy

**Files:**
- Create: `files/usr/libexec/atomic-hyprland/agent-root`, `files/usr/share/polkit-1/actions/org.atomic-hyprland.agent.policy`, `tests/py/test_agent_root.py`
- Modify: `tests/test-agent.sh`, `tests/image-smoke.sh`

**Interfaces:**
- Produces: `pkexec /usr/libexec/atomic-hyprland/agent-root <op> …`. The ops:
  - `unit {start|stop|restart} <unit>`. The unit must match `^[A-Za-z0-9@._:\\-]+\.(service|timer|socket|path|target|mount)$`.
  - `bootc-upgrade`: runs `bootc upgrade`, never `--apply`.
  - `bootc-rollback`.
  - `etc-snapshot <session-dir> <path>`.
  - `etc-write <session-dir> <path>`: content on stdin. It snapshots first, using the same manifest format as `snapshots.snapshot`.
  - `etc-restore <path> <copy>`.

  `<path>`, after `realpath(strict=False)` of its parent plus the name, must be under `/etc/`, and its parent must not be a symlink that leaves `/etc`. `<session-dir>` must resolve under the home of `PKEXEC_UID` (from `pwd`). Copies are `chown`ed to `PKEXEC_UID`. Exit codes: 0 ok, 2 refused (message on stderr), 1 operation failed. The module is standalone and imports no `atomic_agent`, so a compromised user package cannot change it.
- Policy XML: action `org.atomic-hyprland.agent.root`, `org.freedesktop.policykit.exec.path` = the helper; `allow_any`, `allow_inactive` and `allow_active` all `auth_admin_keep`.

- [ ] **Step 1: Write failing tests.** Import the helper with `importlib.machinery.SourceFileLoader` and call its `validate_*` functions and `main(argv, env, run=stub)`:
  - `test_rejects_traversal`: `/etc/../usr/bin/x`.
  - `test_rejects_symlink_escape`: a tmp `fake_etc/link → tmp/usr`, with the helper's `ETC` constant monkeypatched.
  - `test_rejects_foreign_session_dir`.
  - `test_rejects_bad_unit`: `foo;rm`.
  - `test_upgrade_never_applies`: the argv equals `["bootc","upgrade"]`.
  - `test_etc_write_snapshots_first`.

  Shell check: `xmllint --noout` on the policy and `grep -q auth_admin_keep`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. Image-smoke: `check test -x /usr/libexec/atomic-hyprland/agent-root`, `check pkaction --action-id org.atomic-hyprland.agent.root`. If Task 1's finding E is still open, re-run its step on hardware now and record the result in the notes.
- [ ] **Step 5: Commit** `feat(agent): polkit-gated root helper for a fixed set of operations`.

---

### Task 8: System MCP server

**Files:**
- Create: `atomic_agent/servers/system.py`, `files/usr/share/atomic-hyprland/mcp.d/system.json`, `tests/py/test_server_system.py`

**Interfaces:**
- Consumes: `snapshots` (for user-side session dirs). It invokes `agent-root` through `pkexec`.
- Produces tool functions (plain functions wrapped by FastMCP in `main()`; `run` injectable):
  - Read:
    - `journal(unit: str | None = None, user: bool = False, since: str = "-1h", priority: str | None = None, lines: int = 200) -> str`: `journalctl --no-pager -o short-iso [--user] [-u unit] --since <since> [-p prio] -n <lines>`, with `lines` capped at 2000.
    - `unit_status(unit, user=False) -> str`.
    - `failed_units(user=False) -> str`.
    - `bootc_status() -> str`: `rpm-ostree status --json`, which works unprivileged.
  - Change:
    - `restart_unit`, `start_unit`, `stop_unit(unit, user=False)`: user units via `systemctl --user`, system units via `pkexec agent-root unit …`.
    - `bootc_upgrade()`, `bootc_rollback()`.
    - `write_etc_file(path: str, content: str)`: the session folder comes from `HYPR_AGENT_SESSION`.
- `system.json`: `"command": "/usr/libexec/atomic-hyprland/mcp-server", "args": ["system"]`, `readOnlyTools: ["journal","unit_status","failed_units","bootc_status"]`, plus `"toolNotes"`, e.g. `{"restart_unit": "A restart can't be undone, but the service keeps its config.", "bootc_rollback": "Undo with another bootc rollback.", "bootc_upgrade": "Staged only; bootc rollback after reboot reverses it.", "write_etc_file": "Undo restores the file."}`.
- `rootTools` in `system.json`: `restart_unit`, `start_unit`, `stop_unit`, `bootc_upgrade`, `bootc_rollback`, `write_etc_file`. The unit tools count as root even with `user=true`: a rule names the tool, not its arguments, and over-asking is the safe side.

- [ ] **Step 1: Write failing tests:**
  - `test_journal_argv`.
  - `test_journal_caps_lines`.
  - `test_user_restart_uses_systemctl_user`.
  - `test_system_restart_uses_pkexec_helper`.
  - `test_write_etc_passes_content_on_stdin`.
  - `test_bootc_status_unprivileged`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. Image-smoke: `check python3 /tests/mcp-smoke.py system journal unit_status failed_units bootc_status restart_unit write_etc_file`.
- [ ] **Step 5: Commit** `feat(agent): system MCP server (journal, units, bootc)`.

---

### Task 9: Hyprland, screen and notify MCP servers

**Files:**
- Create: `atomic_agent/servers/hyprland.py`, `screen.py`, `notify.py`; `files/usr/share/atomic-hyprland/mcp.d/hyprland.json`, `screen.json`, `notify.json`; `tests/py/test_server_hyprland.py`, `test_server_screen.py`
- Modify: `tests/image-smoke.sh`

**Interfaces:**
- Produces:
  - `hyprland`:
    - Read: `list_windows()`, `list_workspaces()`, `list_monitors()`, `active_window()`, `list_binds()`, each returning the `hyprctl -j` JSON text.
    - Change: `focus_window(address)`, `move_window_to_workspace(address, workspace)`, `resize_window(address, width, height)`, `close_window(address)`, `switch_workspace(workspace)`, `launch(command)`, `reload_config()`.
    - Each change tool goes through `dispatch_expr(tool: str, **args) -> str`, which returns the Lua expression for `hyprctl dispatch`. Pick the `hl.dsp` functions from `/usr/share/hypr/stubs/hl.meta.lua` in the image. `launch` uses `hl.dsp.exec_cmd("uwsm-app -- " .. cmd)`. Strings are quoted with a `lua_str()` helper that escapes `\`, `"` and newlines.
  - `screen`: `capture(target: str = "window", address: str | None = None, output: str | None = None, region: str | None = None) -> str`. It uses `grim` (`-g` for a window, from `hyprctl clients -j` geometry, or for a region; `-o` for an output) into `session_dir($HYPR_AGENT_SESSION)/screens/<ts>.png` and returns the path. It is never read-only.
  - `notify`: `notify(summary: str, body: str = "", urgency: str = "normal") -> str`.
- Registry files: `readOnlyTools` lists the read tools; `screen.capture` and every change tool get `toolNotes`.

- [ ] **Step 1: Write failing tests:**
  - `test_lua_str_escapes`: input `a"b\nc` gives `"a\"b\\nc"`.
  - `test_launch_wraps_uwsm_app`.
  - `test_dispatch_expr_every_change_tool`: each of the seven returns a non-empty string starting with `hl.dsp.`.
  - `test_capture_window_geometry`: stub `hyprctl` JSON `at [10,20]`, `size [300,200]` gives the grim argv `-g "10,20 300x200"`.
  - `test_capture_path_in_session`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. In image-smoke, run each `dispatch_expr()` result through the existing `verify_hypr` probe as `hl.bind("SUPER + F12", <expr>)`, and expect no Lua error. Add `mcp-smoke.py` checks for `hyprland`, `screen` and `notify`.
- [ ] **Step 5: Commit** `feat(agent): Hyprland, screen and notify MCP servers`.

---

### Task 10: Super+A, context capture and ask mode

**Files:**
- Create: `atomic_agent/context.py`, `atomic_agent/agent.py`, `files/usr/bin/hypr-agent`, `files/usr/share/atomic-hyprland/agent/settings.json`, `files/usr/share/atomic-hyprland/agent/instructions.md`, `tests/py/test_context.py`, `tests/py/test_agent.py`
- Modify: `files/usr/share/atomic-hyprland/hypr/binds.lua`, `tests/test-binds.sh`

**Interfaces:**
- Consumes: `load_registry`, `client_entry`, `paths.*`, `ui.choose`.
- Produces, in `context.py`:
  - `window_geometry(active: dict) -> str`, giving `"x,y wxh"`.
  - `terminal_cwd(pid: int, proc: Path = Path("/proc")) -> Path | None`: the deepest descendant whose `comm` is in `{"bash","zsh","fish","elvish","nu","sh","dash"}`, then its `cwd` link.
  - `clipboard_text(run=…, limit: int = 4000) -> str | None`: `None` when `wl-paste --list-types` includes `x-kde-passwordManagerHint` or nothing is copied.
  - `@dataclass Context(screenshot: Path | None, clipboard: str | None, cwd: Path | None)` and `capture(session_dir: Path) -> Context`.
  - `prompt(ctx: Context, menu=…) -> tuple[str, Context] | None`: a wofi dmenu loop showing chip lines (`󰹑 window screenshot  (select to remove)`, `󰅍 clipboard: <first 40 chars>`, `󰉋 <cwd>`). Selecting a chip removes it and re-prompts. Typed text returns `(text, ctx)`; an empty Enter returns `("What's wrong here? Explain the problem on screen and how to fix it.", ctx)`; Escape returns `None`.
- Produces, in `agent.py`:
  - `build_settings(base: dict, rules_path: Path, registry: dict[str, ServerDef]) -> dict`. Start from `base`; add `mcp__<srv>__<tool>` to `permissions.allow` for every `read_only_tools` entry, plus the user rules from `rules_path` (and nothing from `~/.claude/settings.json`); set `hooks.PreToolUse` to the snapshot hook command `hypr-agent hook pre-tool-use` for matcher `Edit|Write|MultiEdit|NotebookEdit`; set `permissions.defaultMode = "default"`.
  - `mcp_config(registry) -> dict`: `{"mcpServers": {name: client_entry(d)} | {"approvals": {"type":"stdio","command":"/usr/libexec/atomic-hyprland/mcp-server","args":["approvals"]}}}`.
  - `agent_env(sid) -> dict[str, str]`: `os.environ` plus `HYPR_AGENT_SESSION=<sid>`. Every claude run (ask, fix, chat) gets it, and the MCP servers claude starts inherit it. If Task 1 shows they don't, put it in each stdio entry's `env` instead.
  - `ask_argv(sid, text, ctx, settings_file, mcp_file) -> list[str]`: `claude -p --session-id <sid> --output-format json --setting-sources project,local --settings <settings_file> --mcp-config <mcp_file> --strict-mcp-config --permission-prompts none --append-system-prompt-file /usr/share/atomic-hyprland/agent/instructions.md`, then the prompt. The prompt names the screenshot path and asks the model to Read it, and includes the clipboard and cwd. Use Task 1's ruling if CLAUDE.md needs `--append-system-prompt-file ~/.claude/CLAUDE.md` too.
  - CLI: `hypr-agent ask`. It captures, prompts, writes the settings and MCP files into `session_dir(sid)`, records `$XDG_RUNTIME_DIR/hypr-agent/ask.pid`, signals waybar (`pkill -RTMIN+10 waybar`), runs claude from the cwd (or `$HOME`), and saves `meta.json` (`sid`, `cwd`, `created`, `mode: "ask"`). It then shows `ui.choose` with the answer (first 300 chars) and `fix` / `chat` / `dismiss`. `fix` starts Task 11's unit.
- `settings.json`:
  - `permissions.allow`: `Read`, `Glob`, `Grep`, `LS`, `WebSearch`, `WebFetch`.
  - `permissions.deny`: `Bash(sudo:*)`, `Bash(pkexec:*)`, `Bash(su:*)`, `Bash(run0:*)`, `Bash(bootc switch:*)`.
- `instructions.md` (agent system prompt; prose, about 40 lines). It must state:
  - make file changes with Edit/Write, not shell;
  - never use sudo; root changes go through the `system` tools;
  - say what you will change before changing it;
  - image-level fixes never change the running `/usr`; they become a PR:
    - run `hypr-agent pr-target` (Task 12) and stop and explain if it exits 3;
    - work in a clone under `~/.local/share/atomic-hyprland/agent/repo`, on a branch `agent/<topic>`;
    - run the repo's host-side tests;
    - open the PR with `gh pr create`, describing the machine (`hostname`, the image version from `rpm-ostree status --json`), what failed and how it was verified;
    - never merge.
- Binds: `SUPER + A` → `hl.dsp.exec_cmd("hypr-agent ask")`.

- [ ] **Step 1: Write failing tests:**
  - `test_window_geometry`.
  - `test_terminal_cwd_finds_deepest_shell`: a fake `/proc` tree with ghostty → bash → elvish.
  - `test_clipboard_skips_password_hint`.
  - `test_prompt_chip_removal_then_text`.
  - `test_prompt_escape_sends_nothing`.
  - `test_empty_enter_default_question`.
  - `test_build_settings_read_only_tools_allowed`: contains `mcp__system__journal`, not `mcp__system__restart_unit`.
  - `test_build_settings_includes_user_rules`.
  - `test_ask_argv_read_only`: contains `--permission-prompts none` and lacks `--permission-prompt-tool`.

  `test-binds.sh`: `check grep -q '"SUPER + A"' "$binds"`, and the bind total stays duplicate-free.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): Super+A asks a read-only agent about the screen`.

---

### Task 11: Fix, chat, stop, undo, review and the snapshot hook entry

**Files:**
- Modify: `atomic_agent/agent.py`, `files/usr/bin/hypr-agent`, `files/usr/share/atomic-hyprland/hypr/binds.lua`, `tests/py/test_agent.py`, `tests/test-binds.sh`

**Interfaces:**
- Consumes: Tasks 5, 6 and 10.
- Produces:
  - `fix_argv(sid, settings_file, mcp_file) -> list[str]`: `claude -p --resume <sid> --output-format json --setting-sources project,local --settings … --mcp-config … --strict-mcp-config --permission-prompt-tool mcp__approvals__prompt --append-system-prompt-file …`, then `"Fix the problem now. Ask before each change; prefer Edit/Write for files."`
  - `chat_argv(sid, settings_file, mcp_file) -> list[str]`: interactive `claude --resume <sid>` with the same isolation flags. Use the permission-prompt tool only if Task 1, finding A says interactive mode supports it.
  - `start_fix(sid) -> str`: `systemd-run --user --unit=hypr-agent-<sid[:8]> --collect -p Type=exec -- hypr-agent run-fix <sid>`. Returns the unit name.
  - `run_fix(sid)`: runs `fix_argv`, then `ui.choose` with a done card. The body is the result's first 300 chars plus the restored-on-undo files from the manifest. The choices are `undo`, `chat`, `dismiss`.
  - `stop_all(run=…) -> None`:
    - `systemctl --user stop 'hypr-agent-*.service'`;
    - kill the PID in `ask.pid`;
    - `ui.answer(id, "deny")` for every pending entry;
    - `makoctl dismiss -a` for notifications from app `hypr-agent` (via `makoctl list` filtering);
    - signal waybar.
  - `undo_session(sid) -> list[str]`: calls `snapshots.undo` with `restore_etc = pkexec agent-root etc-restore`.
  - CLI:
    - `hypr-agent fix <sid>`, `run-fix <sid>`, `chat <sid>`: chat runs `hypr-terminal -e` with `chat_argv` via `uwsm-app`.
    - `stop`.
    - `undo <sid>`.
    - `review`: answers `ui.oldest_pending()`.
    - `hook pre-tool-use`: reads stdin JSON, exits with `hook_pre_tool_use`'s code; `snapshot_etc` = `pkexec agent-root etc-snapshot`.
    - `sessions`: lists sid, mode, created, number of changes.
- Binds: `SUPER + SHIFT + A` → `hypr-agent stop`; `SUPER + Y` → `hypr-agent review`.

- [ ] **Step 1: Write failing tests:**
  - `test_fix_argv_uses_prompt_tool`.
  - `test_agent_argv_ignores_user_settings`. Write `HOME/.claude/settings.json` = `{"permissions":{"allow":["Bash(*)"],"defaultMode":"bypassPermissions"}}`. Then the generated settings file contains no `Bash(*)` and no `bypassPermissions`, and both argvs contain `--setting-sources project,local`.
  - `test_stop_denies_pending`: create a pending entry; a thread in `wait_answer` returns `"deny"` within 1 s of `stop_all` (with stubbed `systemctl` and `makoctl`).
  - `test_start_fix_unit_name`.
  - `test_undo_session_routes_etc_to_helper`.
  - `test_hook_cli_exit_code`.

  `test-binds.sh`: grep checks for `"SUPER + SHIFT + A"` and `"SUPER + Y"`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `bash tests/test-agent.sh && bash tests/test-binds.sh`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): background fix with approvals, stop, undo and chat`.

---

### Task 12: Bar indicator, PR target and the end-to-end check

**Files:**
- Create: `files/usr/libexec/atomic-hyprland/waybar/agent`, `atomic_agent/prtarget.py`, `tests/py/test_waybar_agent.py`, `tests/py/test_prtarget.py`
- Modify:
  - `files/usr/share/atomic-hyprland/waybar/config.jsonc`: add `custom/agent` before `custom/claude`.
  - `files/etc/skel/.config/waybar/style.css`: add `#custom-agent` next to `#custom-claude`, with `.pending` using the warning colour.
  - `Containerfile`: `ARG IMAGE_SOURCE=https://github.com/danmwallace/atomic-hyprland`; the label uses `${IMAGE_SOURCE}`; pass it to `40-finalize.sh` as `$2`.
  - `build/40-finalize.sh`: write `/usr/share/atomic-hyprland/image-source`.
  - `files/usr/bin/hypr-agent`: add `pr-target`.
  - `tests/test-waybar.sh`, `tests/image-smoke.sh`, `tests/test-build-pins.sh` if it pins the label.
  - `README.md`: a short "Agent" section covering Super+A, Super+Y, Super+Shift+A, `hypr-mcp`, `mcp.d` and `permissions.json`.

**Interfaces:**
- Produces:
  - `waybar/agent`: prints JSON. When idle (no `hypr-agent-*` unit active, no live `ask.pid`, no pending), the text is empty. Otherwise the text is `󱚥` plus the pending count when > 0, the class is `running` or `pending`, and the tooltip lists the sessions. Waybar config: `"exec"`, `"return-type": "json"`, `"interval": 2`, `"signal": 10`, `"on-click": "hypr-agent stop"`, `"on-click-right": "hypr-agent review"`.
  - `prtarget.target_repo(source_file=Path("/usr/share/atomic-hyprland/image-source"), conf=Path("/etc/atomic-hyprland/agent.conf")) -> str | None`. `repo=` in `agent.conf` wins over the file; the result is normalised to `owner/name`.
  - `prtarget.can_push(repo, run=…) -> bool`: `gh api repos/<repo> --jq .permissions.push` equal to `true`.
  - `hypr-agent pr-target` prints `owner/name`, or exits 3 with "PRs are off: your GitHub login can't push to <repo>. Fork it and set repo= in /etc/atomic-hyprland/agent.conf".

- [ ] **Step 1: Write failing tests:**
  - `test_idle_prints_empty_text`.
  - `test_pending_class_and_count`.
  - `test_conf_overrides_source`.
  - `test_normalises_url`.
  - `test_cannot_push_disables`.

  `test-waybar.sh`: `custom/agent` sits before `custom/claude` and its `on-click` is `hypr-agent stop`. `image-smoke.sh`: `check grep -qx https://github.com/danmwallace/atomic-hyprland /usr/share/atomic-hyprland/image-source`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all host suites** (the `just test` list without the podman lines). Expected: every suite passes.
- [ ] **Step 5: Commit** `feat(agent): bar indicator, PR target and docs`.
- [ ] **Step 6: End-to-end on hardware, after CI publishes and Dan reboots the Alienware.** Run each case and record the results in the notes file:
  - Super+A over a terminal showing `systemctl --user status nonexistent.service`: an answer card appears.
  - Fix it: approval cards appear for changes, and the indicator shows.
  - Super+Shift+A: everything stops, and the pending card resolves as Deny.
  - An edit to a scratch file in `~/tmp-agent-test`, then Undo from the done card: the file is restored.

  Commit the notes.
