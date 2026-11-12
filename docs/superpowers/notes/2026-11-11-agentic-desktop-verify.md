# Agentic desktop: verification notes (plan Task 1)

Date: 2026-11-11. Probes ran on frmwrk with Claude Code 2.1.321 and the
`claude-haiku` model; flag availability was checked against the image's pinned
2.1.289 (`podman run ghcr.io/danmwallace/atomic-hyprland:44 claude --help`).

## Flags at 2.1.289

All present: `--permission-prompt-tool` (listed inside `--permission-prompts`'
help), `--permission-prompts`, `--setting-sources`, `--settings`,
`--mcp-config`, `--strict-mcp-config`, `--session-id`, `--resume`.
`--append-system-prompt-file` is not listed on its own line but is named in the
help (`--append-system-prompt[-file]`) and works (finding B).

## A. Permission-prompt tool: confirmed

- Claude calls the tool with arguments `{"tool_name": str, "input": dict,
  "tool_use_id": str}`.
- Reply (tool result text, JSON):
  - allow: `{"behavior":"allow","updatedInput":{...the input...}}` — the tool
    then runs with `updatedInput`;
  - deny: `{"behavior":"deny","message":"..."}` — the model sees the message.
- MCP servers started by claude inherit claude's environment
  (`HYPR_AGENT_SESSION` set on the claude process reached the server), so
  `agent_env()` is enough; no per-entry `env` needed.
- Interactive mode: not probed (no TTY in the harness). The help scopes
  `--permission-prompts host` to `--print`; ruling as planned: Open chat uses
  Claude Code's terminal prompts with the same isolated settings and hook.

## B. Settings isolation: differs (CLAUDE.md), ruling below

With a config dir whose `settings.json` allows `Write` and whose `CLAUDE.md`
holds a codeword, and `--permission-prompts none`:

| run | codeword | Write |
|---|---|---|
| default sources | PLUM | allowed (user rule applied) |
| `--setting-sources project,local` | NONE | denied (user rule ignored) |
| same + `--append-system-prompt-file <CLAUDE.md>` | PLUM | — |

- Permission isolation works: user-level allow rules (and so a user-level
  `bypassPermissions` default) do not reach the session.
- The user's `~/.claude/CLAUDE.md` is dropped with the `user` source.
- Login works with the isolated sources (credentials are not a setting source).
- **Ruling:** `hypr-agent` writes one system-prompt file per session:
  `instructions.md` followed by `~/.claude/CLAUDE.md` when it exists, and
  passes it with `--append-system-prompt-file` (one flag; the system prompt is
  recorded at session start and reused on `--resume`). Cost if wrong: the agent
  lacks the user's preferences. Auto-memory under `~/.claude/projects/*/memory`
  is not loaded in isolated sessions; accepted for piece 1 (piece 2 may add it).

## C. Hooks from `--settings` in `-p`: confirmed

- A `PreToolUse` hook (matcher `Edit|Write`) from `--settings` runs in `-p` mode
  with `--setting-sources project,local`, before the permission-prompt tool.
- stdin JSON fields used: `session_id`, `tool_name`, `tool_input.file_path`,
  `hook_event_name` ("PreToolUse"), `permission_mode`.
- `session_id` equals the `--session-id` passed, and stays the same on
  `--resume`.
- Exit code 2 blocks the tool (the file was not created).

## D. python3-mcp: confirmed

- Fedora 44 `python3-mcp-1.26.0-1.fc44.noarch`.
- `from mcp.server.fastmcp import FastMCP`; `@app.tool()`; `app.run()` (stdio).
- `from mcp.types import ToolAnnotations`;
  `@app.tool(annotations=ToolAnnotations(readOnlyHint=True))` round-trips to
  clients.
- Client: `from mcp import ClientSession, StdioServerParameters`,
  `from mcp.client.stdio import stdio_client`.
- It logs "Processing request …" and a pydantic warning to stderr; harmless
  (stdout carries the protocol). Servers set `log_level="WARNING"`.

## E. polkit from a user unit: open

Needs Dan at a Hyprland session (a password dialog appears). Re-checked in
Task 7 on hardware.

## F. Gemini CLI mcpServers: confirmed

`~/.gemini/settings.json` → `mcpServers.<name>` with exactly one of
`command` (+ `args`, `env`, `cwd`), `httpUrl` (streamable HTTP) or `url` (SSE);
optional `headers`, `timeout`, `trust`, `includeTools`, `excludeTools`.
**Ruling:** `sync_gemini` maps Claude-style `{"type":"http","url":U}` to
`{"httpUrl":U}` and `{"type":"sse","url":U}` to `{"url":U}`; stdio entries map
to `{"command":"hypr-mcp","args":["run",name]}`.
