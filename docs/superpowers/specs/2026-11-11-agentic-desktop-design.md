# Agentic desktop: hotkey agent and desktop MCP layer — design

Date: 2026-11-11. Status: draft, shaped in conversation with Dan (mockup of the
hotkey surface picked 2026-11-11); builder check done, its questions settled
under "Builder-check decisions". Piece 1 of 3; see "Scope and order".

## Intent

Dan's daily loop today: something fails in a terminal, he copies the error or
takes a screenshot, switches to Claude, pastes, explains, and then applies the
fix himself. On frmwrk he also runs Claude Code with MCP servers (MikroTik,
Google, the Obsidian vault and its skills, Hermes) as the control centre for his
homelab. He wants "an improved experience of what I am doing now, with more of
a focus on letting the AI drive the car if needed", on every atomic-hyprland
machine.

His words for what the OS should be:

- The agent "should be able to self improve and use the desktop upon approval
  to remediate the issue and submit a PR as needed to update the image."
- "The OS should be malleable from a user perspective as everything in linux is
  a text file, and a hyprland desktop environment is a great foundation."
- "The OS should be extensible via MCP Servers to act as a sort of command and
  control center."

What would make him wince even if it worked: "If it changed things without
asking me first", and if there were no way to "cancel or backout (for example,
if it gives control of the desktop or something)".

The image must stay general-purpose and shareable. Dan wants people to fork it
and build their own OS from it rather than depend on him; the agent's
self-improvement PRs go to whichever fork the machine was built from.

## Scope and order

1. **This design (in the image):** the hotkey agent, the approval and stop/undo
   machinery, the desktop MCP servers, and the MCP drop-in registry.
2. **Later design (Ansible, ansible-homelab-cfg + collections):** Dan's personal
   layer on top of 1: homelab MCP servers (MikroTik, TrueNAS, srv01), the
   Obsidian vault and his skills on each machine, his Claude Code `CLAUDE.md`,
   memory, settings and plugins, local and remote Hermes agents (ai-master)
   as tools and as MCP clients, secrets.
3. **Later design (docs):** fork-and-own instructions: build the image
   yourself, your own cosign key and registry, point the agent at your fork.

Piece 1 ships nothing Dan-specific. It must be useful to a stranger who forks
the repo and has a Claude login.

## Goals

1. Super+A: ask about what is on screen without copying or explaining
   anything, and get an answer without leaving the current window.
2. "Fix it": the agent remediates in the background, asking before every change.
3. A single place to add an MCP server so every agent on the machine gets it.
4. Desktop MCP servers so any agent can see and, with approval, operate the
   desktop and the OS.
5. The agent can propose image changes as a pull request to the machine's own
   repo (self-improvement), never by modifying the running system's `/usr`.
6. Stop and undo are always one action away.

## Non-goals (this piece)

- Synthetic keyboard and mouse input (wtype, ydotool). Dan declined both for the
  image on 2026-11-08; desktop control here means Hyprland's own dispatchers
  (focus, move, launch, close), not typing or clicking for the user. *(My call,
  from that earlier decision; revisit if Dan wants it.)*
- Scheduled or always-on background agents (idea 4 from the 2026-11-11 list).
- Anything personal: homelab servers, Google, the vault, keys (piece 2).
- Fork-and-own docs (piece 3).
- Voice, remote access to the desktop, a chat UI of our own (Claude Code's
  terminal UI is the chat).
- Installing Gemini CLI in the image. The registry writes Gemini's config if
  Gemini CLI is present; installing it is a user/Ansible choice. *(My call.)*

## Hard requirements (Dan's anti-goals)

1. **Nothing changes without asking.** Reading is free. Every action that
   changes state needs an explicit Allow from Dan, unless he has previously
   chosen "Always allow" for that kind of action. This covers: writing or
   deleting any file, running any command that is not on the read-only list,
   any Hyprland dispatcher that changes windows or workspaces, sending a
   notification other than its own status, git commits, pushes and PRs, systemd
   start/stop/restart, bootc upgrade/rollback.
2. **Always a way out.**
   - A stop hotkey kills every running agent session at once; pending approvals
     become Deny.
   - A bar indicator is visible whenever any agent session is running or has an
     approval pending; clicking it stops all sessions.
   - Every file change the agent makes through its edit tools can be undone
     from the "done" card or the command line (see Undo). Shell commands are
     allowed, but when one cannot be undone automatically its approval card
     says so before Dan answers (Dan, 2026-11-11).
   - Pressing Escape in the prompt sends nothing.
3. **What leaves the machine is visible.** The prompt shows what context is
   attached (window screenshot, clipboard, folder) before it is sent, and each
   item can be removed. Screenshots the agent wants later, during a fix, need
   approval like any other action. *(My call: the hotkey is consent for the one
   capture it shows; later captures could include other windows, like mail.)*
4. **No secrets in the image or in shipped files.** The agent uses the user's
   own Claude login; MCP server definitions reference secrets (keyring,
   systemd-creds) rather than containing them.

## Constraints

- bootc image: `/usr` is read-only at runtime. The image ships mechanism and
  defaults; per-user state lives in `$HOME`, per-machine config in `/etc`.
- Image vs Ansible: generic in the image, personal in Ansible (memory:
  image-vs-ansible-split).
- Session plumbing follows the existing pattern: uwsm, systemd user units bound
  to `graphical-session.target`, programs launched with `uwsm-app`.
- Hyprland 0.57 Lua config: binds in `files/usr/share/atomic-hyprland/hypr/binds.lua`
  (no colliding combos; `tests/test-binds.sh` enforces it), dispatchers via
  `hyprctl dispatch 'hl.dsp....'`.
- Claude Code is already in the image (`@anthropic-ai/claude-code`, pinned in
  the Containerfile, installed under `/usr`).
- Image tools are named `hypr-*` (`hypr-power`, `hypr-theme`, `hypr-terminal`).
- Tests: host-side shell tests under `tests/`, wired into `just test`, plus
  in-image checks in `tests/image-smoke.sh`. Write the test first.
- New third-party package sources (a COPR, an npm or PyPI package not already
  used) need Dan's explicit approval and are named in the commit body.
- Multiple-machine reality: the Alienware (NVIDIA, Ghostty) and the T430
  (Intel HD 4000, Alacritty via `hypr-terminal`) must both work.

## Design

### 1. Asking (Super+A)

- Super+A opens a one-line prompt over the current window (mockup "A, quick
  ask"). It shows chips for the attached context:
  - a screenshot of the focused window (geometry from `hyprctl activewindow -j`,
    captured with `grim`),
  - the clipboard text, skipped when the clipboard offers the password-manager
    hint type (`x-kde-passwordManagerHint`),
  - the working folder of the focused terminal (the shell under the terminal's
    PID, via `/proc/<pid>/cwd`), when the focused window is a terminal.
- Typing a question and pressing Enter sends it; Enter on an empty prompt means
  "what's wrong here?". Escape sends nothing.
- The ask runs read-only: the agent gets only the read tools (below), so it
  needs no approvals and answers quickly.
- The answer arrives as a notification card with **Fix it**, **Open chat**,
  **Dismiss**. A long answer is truncated on the card; Open chat shows it whole.
- Terminals do not expose their scrollback reliably, so the screenshot is how the
  model reads the error. Vision models read terminal text well.

### 2. Fixing, out of sight (Dan's choice)

- **Fix it** continues the same agent session in the background with the change
  tools enabled behind approvals. The session runs as its own transient systemd
  user unit (for example `hypr-agent@<session>`), so it is logged in the journal
  and can be stopped like any unit.
- Each state-changing step sends an approval card: what it wants to do, in plain
  words and as the literal command or diff, whether it can be undone, and
  **Allow / Deny / Always allow this kind**.
- An approval not answered in 10 minutes becomes Deny. *(My call.)*
- It ends with a **done** card: what it changed, which "always allow" rules it
  relied on, and **Undo**.
- **Open chat** (from any card) resumes the same session in a terminal
  (`claude --resume <session>` in `hypr-terminal`) so Dan can watch or steer.

### 3. Approvals, "always allow", stop and undo

- Approvals hook into Claude Code's own permission system: in headless mode the
  permission prompt is delegated to an MCP tool (`--permission-prompt-tool`)
  provided by the image's approvals server, which shows the card and returns the
  decision. The same rules then apply whether Dan uses the hotkey or a normal
  Claude Code session.
- "Always allow" rules are written in Claude Code's permission-rule syntax to a
  dedicated, human-readable file in `~/.config/atomic-hyprland/agent/`, loaded
  by every agent session. Dan can read and edit it; deleting a line revokes it.
- Stop: a hotkey (my call: Super+Shift+A, if `test-binds.sh` shows no clash)
  and the bar indicator both run `hypr-agent stop`, which stops every
  `hypr-agent@*` unit and denies pending approvals.
- Undo:
  - before the agent writes or deletes a file through Edit/Write, the approvals
    server saves the original into the session's state folder
    (`~/.local/state/atomic-hyprland/agent/<session>/`); for files outside
    `$HOME` the root helper (below) takes the snapshot;
  - Bash commands are not snapshotted. The agent's instructions tell it to make
    file changes with Edit/Write, and a Bash approval card states "can't be
    undone automatically" unless the command is known to be reversible;
  - `hypr-agent undo <session>` (and the done card's Undo) restores them, in
    reverse order;
  - for an action that is not a file change (restarting a service, an upgrade),
    the approval card says how to reverse it or that it cannot be reversed;
  - image-level changes only ever arrive as PRs, and `bootc rollback` is the
    backstop for a bad image.

### 3a. Root actions (Dan, 2026-11-11)

- The agent runs as the user and never gets general root. A small root helper
  (a system service, activated on demand) performs a fixed list of privileged
  operations only: restart/start/stop a system unit, `bootc upgrade` (stage
  only), `bootc rollback`, snapshot a file outside `$HOME`, write or restore a
  file under `/etc`.
- Each operation is a polkit action. Flow: the approval card first (what and
  why, Allow/Deny), then on Allow the polkit dialog (hyprpolkitagent) asks for
  the password; the image's policy is `auth_admin_keep`, so one password covers
  about five minutes.
- A machine owner can relax this with a polkit rule (for example, wheel members
  without a password); on Dan's machines Ansible does that in piece 2. The
  image default keeps the password.
- Root actions are never "always allowable" (see Builder-check decisions).

### 4. Desktop MCP servers (shipped in the image)

Read tools need no approval; change tools go through approvals.

| Server | Read | Change (approval) |
|---|---|---|
| hyprland | windows, workspaces, monitors, focused window, binds | focus, move, resize, close, launch an app, switch workspace, reload config |
| screen | — (the hotkey capture is attached by `hypr-agent`, not by a tool) | capture window, output or region |
| notify | — | post a notification (its own status cards are not gated) |
| system | journal (user and system), unit status, failed units, `bootc status` | start/stop/restart a unit, `bootc upgrade` (stage only), `bootc rollback` |
| approvals | — | internal: the permission-prompt tool and undo snapshots |

The image never offers `bootc switch` to an agent. Files and shell commands go
through Claude Code's own tools (Read/Edit/Bash), under the same approvals.

### 5. MCP drop-in registry

- Server definitions are small JSON files in the usual MCP shape (`command`,
  `args`, `env`, or `type` + `url`), one server per file, in three folders:
  1. `/usr/share/atomic-hyprland/mcp.d/` (image defaults),
  2. `/etc/atomic-hyprland/mcp.d/` (machine, e.g. via Ansible),
  3. `~/.config/atomic-hyprland/mcp.d/` (user, by hand or via Ansible).
  A later folder overrides a same-named file from an earlier one; a file
  containing `"disabled": true` turns a server off.
- `env` values may name a secret instead of containing it (lookup from the
  keyring or systemd-creds), resolved when the server starts.
- A file may list `readOnlyTools` (see Builder-check decisions 4).
- `hypr-mcp sync` writes the merged set into each agent's own config:
  Claude Code (user scope) and Gemini CLI (`~/.gemini/settings.json`, only if
  Gemini CLI is installed). Hermes is piece 2. It runs
  at login and whenever a registry folder changes (a systemd path unit). Entries
  it writes are marked as managed, and servers the user added by hand are left
  alone.
- Not Claude Code's `managed-mcp.json`: that file takes exclusive control and
  would block servers users add themselves.

### 6. Self-improvement PRs

- When a fix belongs in the image, the agent proposes a PR instead of changing
  the running system. The target repo comes from the image's
  `org.opencontainers.image.source` label (the fork the machine was built from),
  overridable in `/etc/atomic-hyprland/agent.conf`.
- It works in its own clone under `~/.local/share/atomic-hyprland/agent/`,
  on a `agent/<topic>` branch, runs the host-side tests, and opens the PR with
  the user's own `gh` login. Commit, push and PR creation each need approval. It
  never merges.
- The PR description says which machine, what failed, and how it was verified.

## Builder-check decisions

Settled after the builder check (2026-11-11). Dan decided the first two; the
rest are my calls, marked for his review.

1. **Root (Dan):** the root helper with polkit `auth_admin_keep`, after the
   approval card; section 3a.
2. **Undo scope (Dan):** Edit/Write changes are snapshotted and undoable; Bash
   changes are allowed and labelled when not undoable; requirement 2 and
   section 3.
3. **Which sessions the guarantees cover (my call):** the approval, stop, undo
   and indicator machinery covers `hypr-agent` sessions only. Dan's ordinary
   Claude Code sessions keep Claude Code's own terminal prompts. The agent's
   permissions are isolated from his: `hypr-agent` loads its own settings and
   permission rules (not `~/.claude/settings.json` permissions), so a broad
   allow rule or a bypass mode in his personal settings can never skip an
   approval card, and an "Always allow" clicked on a card never loosens his
   interactive sessions. CLAUDE.md and memory still load, so the agent knows
   him. "Open chat" resumes the session in a terminal with the same isolated
   settings and the same permission-prompt tool, so approvals stay cards and
   snapshots continue.
4. **Read vs change for registry servers (my call):** a registry file may list
   `readOnlyTools`. Ask mode gets the image's read tools plus those; every
   other third-party tool is treated as a change and gated in Fix mode. The
   image's own servers declare their read tools the same way.
5. **Gemini (my call):** piece 1's agent is Claude-only. Gemini CLI receives
   the registry sync (if installed) and nothing else; a Gemini backend for
   `hypr-agent` is a later piece with its own approvals path.
6. **MCP implementation (my call):** Python with the official MCP SDK from
   Fedora (`python3-mcp`, in the `fedora` repo; no new package source). The
   image already ships python3, and the waybar helpers are Python.
7. **Hermes (my call):** moves to piece 2. Hermes runs as its own `hermes`
   user, and giving another user's agent the desktop socket and screen is a
   personal security decision. `hypr-mcp sync` writes Claude Code and Gemini
   config only.
8. **"Always allow" breadth (my call):** the card generates the narrowest
   useful rule: one MCP tool, one command prefix (e.g. `Bash(systemctl --user
   restart waybar:*)`), or one path glob, and shows the rule before saving it.
   Never always-allowable: root actions, `git push`, PR creation, `bootc`
   upgrade/rollback, deleting files, and any screenshot.
9. **PR target (my call):** self-improvement PRs are enabled only when the
   target repo (label or `agent.conf`) is one the user's `gh` login can push
   to. Otherwise the agent says so and suggests forking; it never opens PRs
   from a stranger's login against Dan's repo.

## Left to the builder

- Process layout of the Python servers and `hypr-agent` (dependencies from
  Fedora packages, installed at image build, nothing fetched at runtime; any
  dependency outside Fedora's repos needs Dan's approval).
- The approval card surface. mako (the image's notification daemon) supports
  actions but does not draw buttons; choose between mako plus an action menu,
  a notification daemon that draws buttons, or a small dedicated popup. The
  criteria are: one click or one key to answer, readable command/diff, works
  over a fullscreen window, and themed by `hypr-theme`.
- The prompt surface (wofi in dmenu mode or a small layer-shell popup), as long
  as it shows removable context chips and Escape sends nothing.
- The bar indicator's look (it belongs next to `custom/claude`).
- Exact tool names and schemas, the `hypr-agent` subcommands beyond
  `ask`, `stop`, `undo`, `chat`, and how the Gemini backend is selected.
- Test strategy details, in the repo's host-test plus image-smoke style.

## Verify early (assumptions to check before planning around them)

- Claude Code headless: `--permission-prompt-tool`, `--resume`, `--mcp-config`
  and settings-file loading behave as assumed at the pinned version, including
  a way to keep the user's settings-file permissions out of `hypr-agent`
  sessions while CLAUDE.md and memory still load (decision 3).
- `python3-mcp` 1.26.0 (Fedora 44) covers the stdio server features needed.
- Gemini CLI's `settings.json` `mcpServers` format.
- Wayland clipboard: whether Bitwarden (Dan's password manager, via Flatpak)
  sets the password-manager hint type.
