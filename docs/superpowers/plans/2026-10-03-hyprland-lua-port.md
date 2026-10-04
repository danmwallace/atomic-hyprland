# Hyprland Lua Config Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the role's `hyprland.conf.j2` with a split Lua config so the image survives Hyprland 0.57, and fold in the Nerd Font, `hyprland-guiutils`, the Waybar updates-module removal and the transitional 0.56 pin.

**Architecture:** `danmwallace.fedora.hyprland` renders `hyprland.lua` (palette table plus seven `require`s) and `conf/*.lua` modules under `~/.config/hypr/`; `local.lua` replaces `local.conf` as the never-managed override. The image pins the new role tag, drops the 0.56 pin, and its smoke test gates on `Hyprland --verify-config` printing `config ok` for the skel tree. The VM takes the new image via `bootc upgrade`.

**Tech Stack:** Ansible role (Jinja2 templates, molecule with podman), Hyprland 0.56 Lua API (`hl.*`, stub at `/usr/share/hypr/stubs/hl.meta.lua`), podman/bootc image build driven by `just`, bash test scripts run inside the image.

**Spec:** `docs/superpowers/specs/2026-10-03-hyprland-lua-port-design.md` (this repo, branch `dw/lua-port`). Read it first; the construct mapping table there is the authority for every Lua line below.

## Global Constraints

- Role repo: `~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora`, work on branch `dw/lua-config`, release as **1.2.0** (CHANGELOG under Changed/Added/Removed), tag `v1.2.0` after squash-merge.
- Image repo: `~/Code/atomic-hyprland`, branch `dw/lua-port`.
- Hyprland in the image: 0.56.2 from COPR `lionheartp/Hyprland`. Transitional pin `hyprland-0.56*` in `build/packages.txt` exists only between Task 1 and Task 7.
- Nerd Font: `https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/RobotoMono.tar.xz`, sha256 `61f53438b240a00c87c92dc2c372db0bbb264473b36a8144ea62babf787f8383`, installed under `/usr/share/fonts/roboto-mono-nerd/`. Family registers as "RobotoMono Nerd Font Propo"; the configs keep `RobotoMonoNerdFontPropo`.
- Trim list (spec): `browser = "firefox"`; autostart drops `tailscale up`, both `flatpak run` lines, `xhost +SI:localuser:$(whoami)`; duplicated layer rules and commented window rules dropped. Everything else is reproduced.
- Never render `hyprland.conf` or `local.conf` again; never delete them from existing homes.
- Code style: 2-space YAML/Lua tables as in upstream example (4-space inside `hl.config` tables is also fine, be consistent within a file), LF, trailing newline, no trailing whitespace. Ansible: FQCN, desired-state task names, idempotent, `ansible-lint` production profile clean.
- Commits: Conventional Commits, imperative, ≤72-char subject, end with the session attribution lines.
- `just qcow2`-style sudo steps are not needed in this plan. `tofu` is not touched. The VM reboot in Task 8 is announced to Dan before it happens (he may be logged in).

## Review Focus

1. **A Lua error in one module must not blank the desktop.** Expectation: a typo in `binds.lua` leaves monitors, autostart and look intact. Pinned in Task 6's smoke test (inject a bad line into a copy of `conf/binds.lua`, verify `--verify-config` still reports the other modules loaded and the error names `binds.lua`).
2. **`local.lua` missing must be silent.** Expectation: a fresh home with no `local.lua` starts without an error line. Pinned in Task 2's verify playbook (render tree without `local.lua`, `--verify-config` prints `config ok`).
3. **A home that still has `local.conf` and `hyprland.conf` must switch over cleanly.** Expectation: after the image upgrade the VM session uses the Lua config and the old files are ignored. Pinned in Task 6 (`test-sync-dotfiles.sh` seeds `hyprland.conf` + `local.conf` into HOME, runs the sync, asserts they still exist untouched and `local.lua` was created) and Task 8 (VM check).
4. **The font must resolve under the name the configs use, not just be on disk.** Expectation: Waybar's `RobotoMonoNerdFontPropo` renders Nerd glyphs. Pinned in Task 4's smoke check `fc-match -f '%{family}' RobotoMonoNerdFontPropo` containing `Nerd Font Propo`.
5. **The font task must not re-download every run.** Expectation: the role is idempotent on hosts with the font installed. Pinned in Task 4 (molecule idempotence on the skel scenario, and `get_url` guarded by the marker file).

---

### Task 1: Transitional 0.56 pin in the image

**Files:**
- Modify: `~/Code/atomic-hyprland/build/packages.txt`
- Modify: `~/Code/atomic-hyprland/tests/image-smoke.sh`

**Interfaces:**
- Produces: `hyprland-0.56*` installed before the role runs, so the role's `hyprland` package resolves to it. Removed again in Task 7.

- [ ] **Step 1: Write the failing smoke check**

Append to `tests/image-smoke.sh` just after the `check rpm -q hyprland hyprlock ...` line:

```bash
# Transitional: the .conf-to-Lua port targets 0.56; a COPR bump must fail the build, not ship.
check bash -c 'rpm -q --qf "%{VERSION}\n" hyprland | grep -q "^0\.56\."'
```

- [ ] **Step 2: Run it to verify it currently passes (the pin is a guard, not a change)**

Run: `cd ~/Code/atomic-hyprland && podman run --rm -v ./tests:/tests:ro,Z ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/image-smoke.sh | grep 'VERSION'`
Expected: `ok    bash -c rpm -q --qf ...` (0.56.2 is installed today). This check is pinned so the version is asserted by the test, not assumed.

- [ ] **Step 3: Add the pin to the package list**

In `build/packages.txt`, add before `# wallpaper referenced by ...`:

```
# Transitional: hold Hyprland at 0.56 until the role's Lua config lands (removed in the same change).
hyprland-0.56*
```

- [ ] **Step 4: Verify dnf accepts the glob (no rebuild needed yet)**

Run: `podman run --rm ghcr.io/danmwallace/atomic-hyprland:44 bash -c 'dnf -y copr enable lionheartp/Hyprland >/dev/null 2>&1; dnf -q repoquery "hyprland-0.56*" | head -3'`
Expected: at least one `hyprland-0:0.56.2-...` line.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/atomic-hyprland
git add build/packages.txt tests/image-smoke.sh
git commit -m "build: pin Hyprland to 0.56 until the Lua config port lands

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 2: Role scaffolding: entry file, monitors, env, autostart, task wiring, verify helper

**Files (in the role repo, branch `dw/lua-config`):**
- Create: `roles/hyprland/templates/home/config/hypr/hyprland.lua.j2`
- Create: `roles/hyprland/templates/home/config/hypr/conf/monitors.lua.j2`
- Create: `roles/hyprland/templates/home/config/hypr/conf/env.lua.j2`
- Create: `roles/hyprland/templates/home/config/hypr/conf/autostart.lua.j2`
- Modify: `roles/hyprland/tasks/main.yml` (directory loop, template loop, local.conf task)
- Create: `roles/hyprland/molecule/verify-lua.sh` (helper used by both scenarios' verify and by the fast local loop)
- Modify: `roles/hyprland/molecule/skel/verify.yml`
- Modify: `roles/hyprland/molecule/default/verify.yml`
- Delete at the end of Task 3 (not here): `roles/hyprland/templates/home/config/hypr/hyprland.conf.j2`

**Interfaces:**
- Produces: global Lua table `palette` with every key of `vars/themes/<theme>.yml` as a hex string without `#` (`palette.accent_primary == "88c0d0"` for nord). Produces `require("conf.monitors")`, `require("conf.env")`, `require("conf.autostart")` lines; Task 3 adds `look`, `input`, `binds`, `rules` requires. Produces `local.lua` created once with `force: false`.
- Produces `molecule/verify-lua.sh <hypr-dir>`: copies `<hypr-dir>` into a temp HOME and runs `Hyprland --verify-config --i-am-really-stupid`, exits non-zero unless output contains `config ok` and contains none of `attempt to|stack traceback|Config error`.

**Fast local loop (used in every role task).** Render the role's templates with a throwaway playbook and verify inside the image, no molecule needed:

```bash
# save as /tmp/claude-render/render.sh (outside the repo)
#!/usr/bin/bash
set -euo pipefail
ROLE=~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora/roles/hyprland
OUT=/tmp/claude-render/hypr; rm -rf "$OUT"; mkdir -p "$OUT/conf"
cat > /tmp/claude-render/render.yml <<EOF
- hosts: localhost
  connection: local
  gather_facts: false
  vars:
    hyprland_wallpaper: /usr/share/backgrounds/images/earth_from_space.jpg
  vars_files:
    - $ROLE/vars/themes/nord.yml
  tasks:
    - ansible.builtin.template:
        src: "$ROLE/templates/home/config/hypr/{{ item }}.j2"
        dest: "$OUT/{{ item }}"
        mode: "0644"
      loop: "{{ lookup('ansible.builtin.fileglob', '$ROLE/templates/home/config/hypr/*.lua.j2', wantlist=True) | map('basename') | map('regex_replace', '\\\\.j2$', '') | list
             + lookup('ansible.builtin.fileglob', '$ROLE/templates/home/config/hypr/conf/*.lua.j2', wantlist=True) | map('basename') | map('regex_replace', '\\\\.j2$', '') | map('regex_replace', '^', 'conf/') | list }}"
EOF
ansible-playbook -i localhost, /tmp/claude-render/render.yml >/dev/null
printf '# local overrides\n' > "$OUT/local.lua"
"$ROLE/molecule/verify-lua.sh" "$OUT"
```

`molecule/verify-lua.sh` itself (committed in the role, mode 0755):

```bash
#!/usr/bin/bash
# Verify a rendered ~/.config/hypr tree with Hyprland's own parser.
# Usage: verify-lua.sh <hypr-dir>   (runs in a container when not already inside one)
set -uo pipefail
dir="${1:?hypr dir}"
image="${HYPR_VERIFY_IMAGE:-ghcr.io/danmwallace/atomic-hyprland:44}"

run_verify() {
    export HOME="$(mktemp -d)" XDG_RUNTIME_DIR="$(mktemp -d)"
    mkdir -p "$HOME/.config" && cp -r "$1" "$HOME/.config/hypr"
    Hyprland --verify-config --i-am-really-stupid 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
}

if command -v Hyprland >/dev/null 2>&1; then
    out="$(run_verify "$dir")"
else
    out="$(podman run --rm -v "$dir:/src:ro,Z" -v "$0:/verify.sh:ro,Z" "$image" bash /verify.sh /src)"
fi
echo "$out" | grep -v '^DEBUG' | tail -15
if echo "$out" | grep -q 'config ok' && ! echo "$out" | grep -Eq 'attempt to|stack traceback|Config error'; then
    echo "verify-lua: ok"; exit 0
fi
echo "verify-lua: FAILED" >&2; exit 1
```

- [ ] **Step 1: Write the failing verify assertions and the helper**

Create `molecule/verify-lua.sh` with the content above. In `molecule/skel/verify.yml` replace the whole task list with:

```yaml
---
- name: Verify skel mode
  hosts: molecule
  gather_facts: false
  tasks:
    - name: Stat files rendered into /etc/skel
      ansible.builtin.stat:
        path: "{{ item }}"
      loop:
        - /etc/skel/.config/hypr/hyprland.lua
        - /etc/skel/.config/hypr/conf/monitors.lua
        - /etc/skel/.config/hypr/conf/env.lua
        - /etc/skel/.config/hypr/conf/autostart.lua
        - /etc/skel/.config/hypr/conf/look.lua
        - /etc/skel/.config/hypr/conf/input.lua
        - /etc/skel/.config/hypr/conf/binds.lua
        - /etc/skel/.config/hypr/conf/rules.lua
        - /etc/skel/.config/hypr/local.lua
        - /etc/skel/.config/hypr/hyprlock.conf
        - /etc/skel/.config/waybar/config
        - /etc/skel/.config/alacritty/alacritty.toml
      register: hyprland_skel_files

    - name: Assert skel files exist and are root-owned
      ansible.builtin.assert:
        that:
          - item.stat.exists
          - item.stat.isreg
          - item.stat.pw_name == 'root'
      loop: "{{ hyprland_skel_files.results }}"
      loop_control:
        label: "{{ item.item }}"

    - name: Stat files the role must no longer render
      ansible.builtin.stat:
        path: "{{ item }}"
      loop:
        - /etc/skel/.config/hypr/hyprland.conf
        - /etc/skel/.config/hypr/local.conf
        - /etc/systemd/system/default.target
        - /home/root
      register: hyprland_skel_forbidden

    - name: Assert the old config format and service changes are absent
      ansible.builtin.assert:
        that: not item.stat.exists
      loop: "{{ hyprland_skel_forbidden.results }}"
      loop_control:
        label: "{{ item.item }}"

    - name: Read rendered hyprland.lua
      ansible.builtin.slurp:
        src: /etc/skel/.config/hypr/hyprland.lua
      register: hyprland_skel_entry

    - name: Assert the entry file carries the Nord palette and the override hook
      vars:
        rendered: "{{ hyprland_skel_entry.content | b64decode }}"
      ansible.builtin.assert:
        that:
          - "'accent_primary = \"88c0d0\"' in rendered"
          - "'pcall(require, \"local\")' in rendered"

    - name: Copy the verify helper into the instance
      ansible.builtin.copy:
        src: ../verify-lua.sh
        dest: /usr/local/bin/verify-lua.sh
        mode: "0755"

    - name: Verify the rendered tree parses with Hyprland (no local.lua present)
      ansible.builtin.command: /usr/local/bin/verify-lua.sh /etc/skel/.config/hypr
      changed_when: false
      register: hyprland_skel_verify

    - name: Verify the rendered tree parses with a local.lua that sets a monitor
      ansible.builtin.shell: |
        set -e
        tmp=$(mktemp -d); cp -r /etc/skel/.config/hypr "$tmp/hypr"
        printf 'hl.monitor({ output = "Virtual-1", mode = "preferred", position = "auto", scale = 1 })\n' > "$tmp/hypr/local.lua"
        /usr/local/bin/verify-lua.sh "$tmp/hypr"
      changed_when: false
```

The `local.lua` rendered by the role is a comment-only file, so the first verify covers "present but empty"; delete it before the first verify to cover "absent" (Review Focus 2): add `rm -f` as a pre-step in that command: change the command to `bash -c 'tmp=$(mktemp -d); cp -r /etc/skel/.config/hypr "$tmp/hypr"; rm -f "$tmp/hypr/local.lua"; /usr/local/bin/verify-lua.sh "$tmp/hypr"'`.

In `molecule/default/verify.yml` replace the dotfile stat list with the same twelve paths under `/home/hyprtest/` (owner `hyprtest`), keep the SDDM check, and replace the "Nord palette" assertion by slurping `/home/hyprtest/.config/hypr/hyprland.lua` and asserting `'accent_primary = "88c0d0"' in rendered`. Also copy and run `verify-lua.sh` against `/home/hyprtest/.config/hypr` exactly as above.

- [ ] **Step 2: Run the fast loop to verify it fails**

Run: `bash /tmp/claude-render/render.sh`
Expected: `ansible-playbook` fails because no `*.lua.j2` exists yet (fileglob empty → template loop empty → `verify-lua.sh` finds no `hyprland.lua` → Hyprland generates its example config and prints `config ok`). That passing-by-accident outcome is the reason the helper must also assert the entry file exists: add to `verify-lua.sh`, before `run_verify`: `[[ -f "$dir/hyprland.lua" ]] || { echo "verify-lua: no hyprland.lua in $dir" >&2; exit 1; }`. Re-run: `verify-lua: no hyprland.lua`, exit 1. That is the RED.

- [ ] **Step 3: Write the entry template**

`templates/home/config/hypr/hyprland.lua.j2`:

```lua
-- {{ ansible_managed }}
-- Entry point. Theme values come from vars/themes/{{ hyprland_theme }}.yml;
-- each conf/*.lua module reads the global `palette` table.

palette = {
{% for key, value in hyprland_palette.items() %}
  {{ key }} = "{{ value }}",
{% endfor %}
}

-- Each require runs in its own error scope: a broken module logs and the
-- rest still load.
require("conf.monitors")
require("conf.autostart")
require("conf.env")
require("conf.look")
require("conf.input")
require("conf.binds")
require("conf.rules")

-- Per-machine overrides (VM monitor, NVIDIA env, ...). Created once by the
-- role, never managed afterwards. Missing file is not an error.
pcall(require, "local")
```

- [ ] **Step 4: Write monitors, env and autostart**

`conf/monitors.lua.j2`:

```lua
-- {{ ansible_managed }}
-- Dan's displays, matched by EDID description; anything else gets the fallback.
hl.monitor({ output = "desc:BOE 0x0BCA",                              mode = "2256x1504@60",  position = "auto-left",  scale = 2 })
hl.monitor({ output = "desc:LG Electronics LG TV SSCR2 0x01010101",   mode = "3840x2160@120", position = "auto-right", scale = 1 })
hl.monitor({ output = "desc:Pixio USA PX277 Pro 0x00000001",         mode = "2560x1440@144", position = "auto-right", scale = 1 })
hl.monitor({ output = "",                                            mode = "preferred",     position = "auto",       scale = "auto" })
```

`conf/env.lua.j2`:

```lua
-- {{ ansible_managed }}
hl.env("XDG_CURRENT_DESKTOP", "Hyprland")
hl.env("XDG_SESSION_TYPE", "wayland")
hl.env("XDG_SESSION_DESKTOP", "Hyprland")
hl.env("HYPRCURSOR_THEME", palette.cursor_theme)
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("QT_QPA_PLATFORM", "wayland;xcb")
hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")
hl.env("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")
hl.env("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
hl.env("GDK_BACKEND", "wayland,x11")
hl.env("MOZ_ENABLE_WAYLAND", "1")
```

`conf/autostart.lua.j2` (trimmed per spec):

```lua
-- {{ ansible_managed }}
hl.on("hyprland.start", function()
  hl.exec_cmd("gnome-keyring-daemon --start --components=secrets")
  hl.exec_cmd("dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP")
  hl.exec_cmd("systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP")
  hl.exec_cmd("systemctl --user start xdg-desktop-portal-hyprland")
  hl.exec_cmd("systemctl --user start xdg-desktop-portal-gtk")
  hl.exec_cmd("systemctl --user start hyprpolkitagent")
  hl.exec_cmd("swaybg -m fill -i {{ hyprland_wallpaper }}")
  hl.exec_cmd("waybar")
  hl.exec_cmd("nm-applet --indicator")
  hl.exec_cmd("wl-paste --watch cliphist store")
  hl.exec_cmd("rm \"$HOME/.cache/cliphist/db\"")
  hl.exec_cmd("hypridle")
end)
```

- [ ] **Step 5: Wire the role tasks**

In `tasks/main.yml`:

1. Directory loop: add `- hypr/conf` after `- hypr/scripts`.
2. Template loop: replace the `hyprland.conf.j2` item with:
   ```yaml
    - src: home/config/hypr/hyprland.lua.j2
      dest: hypr/hyprland.lua
    - src: home/config/hypr/conf/monitors.lua.j2
      dest: hypr/conf/monitors.lua
    - src: home/config/hypr/conf/env.lua.j2
      dest: hypr/conf/env.lua
    - src: home/config/hypr/conf/autostart.lua.j2
      dest: hypr/conf/autostart.lua
    - src: home/config/hypr/conf/look.lua.j2
      dest: hypr/conf/look.lua
    - src: home/config/hypr/conf/input.lua.j2
      dest: hypr/conf/input.lua
    - src: home/config/hypr/conf/binds.lua.j2
      dest: hypr/conf/binds.lua
    - src: home/config/hypr/conf/rules.lua.j2
      dest: hypr/conf/rules.lua
   ```
   (the four Task 3 templates are listed now; until Task 3 creates them, create them as placeholder files containing only `-- {{ ansible_managed }}` so the loop and the fast loop work. Task 3 fills them.)
3. Replace the `local.conf` task:
   ```yaml
   - name: "Ensure a per-machine local.lua exists (never overwritten)"
     ansible.builtin.copy:
       content: "-- Per-machine Hyprland overrides, loaded last by hyprland.lua. Never managed.\n"
       dest: "{{ hyprland_home_dir }}/.config/hypr/local.lua"
       owner: "{{ hyprland_file_owner }}"
       group: "{{ hyprland_file_owner }}"
       mode: "0644"
       force: false
     become: true
     become_user: "{{ hyprland_file_owner }}"
   ```

- [ ] **Step 6: Run the fast loop to verify it passes**

Run: `bash /tmp/claude-render/render.sh`
Expected: last line `verify-lua: ok`, with `config ok` in the tail above it. If Hyprland complains about `scale = "auto"` on the fallback monitor, use `scale = 1` (the upstream example uses `"auto"`; the stub decides).

- [ ] **Step 7: Lint and commit**

```bash
cd ~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora
ansible-lint
git add roles/hyprland
git commit -m "feat(hyprland): Lua config entry, monitors, env, autostart; verify helper

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 3: look, input, binds, rules; delete the .conf template

**Files:**
- Create (replace placeholders): `conf/look.lua.j2`, `conf/input.lua.j2`, `conf/binds.lua.j2`, `conf/rules.lua.j2`
- Delete: `templates/home/config/hypr/hyprland.conf.j2`

**Interfaces:**
- Consumes `palette` from Task 2.
- Produces the complete rendered tree; `verify-lua.sh` must print `verify-lua: ok`.

- [ ] **Step 1: Write a failing check for the binds**

Add to `/tmp/claude-render/render.sh` after the verify line:

```bash
grep -q 'hl.dsp.exec_cmd(terminal)' /tmp/claude-render/hypr/conf/binds.lua
grep -q 'switch:on:Lid Switch' /tmp/claude-render/hypr/conf/binds.lua
grep -c '^hl.bind(' /tmp/claude-render/hypr/conf/binds.lua | grep -qE '^(5[0-9]|6[0-9])$'   # 84 binds minus the 30 generated by the loop = 54 literal lines
grep -q 'hl.layer_rule({ match = { namespace = "waybar" }, blur = true })' /tmp/claude-render/hypr/conf/rules.lua
grep -q 'swallow_regex' /tmp/claude-render/hypr/conf/look.lua
echo "content checks: ok"
```

Run: `bash /tmp/claude-render/render.sh`
Expected: the first `grep -q` fails (placeholder file), exit non-zero.

- [ ] **Step 2: look.lua**

`conf/look.lua.j2`:

```lua
-- {{ ansible_managed }}
local function rgba(hex, alpha) return "rgba(" .. hex .. alpha .. ")" end

hl.config({
  general = {
    gaps_in = 5,
    gaps_out = 20,
    border_size = 2,
    col = {
      active_border = {
        colors = { rgba(palette.accent_primary, "ee"), rgba(palette.accent_secondary, "ee"), rgba(palette.accent_tertiary, "ee") },
        angle = 45,
      },
      inactive_border = rgba(palette.bg_dark, "aa"),
    },
    resize_on_border = true,
    extend_border_grab_area = 15,
    hover_icon_on_border = true,
    allow_tearing = false,
    layout = "dwindle",
  },
  decoration = {
    rounding = 10,
    active_opacity = 1.0,
    inactive_opacity = 0.95,
    fullscreen_opacity = 1.0,
    blur = {
      enabled = true,
      size = 5,
      passes = 2,
      ignore_opacity = true,
      new_optimizations = true,
      xray = false,
      noise = 0.0117,
      contrast = 1.0,
      brightness = 1.0,
      vibrancy = 0.1696,
      vibrancy_darkness = 0.0,
      popups = true,
      popups_ignorealpha = 0.2,
    },
    dim_inactive = false,
    dim_strength = 0.05,
  },
  animations = { enabled = true },
  dwindle = {
    preserve_split = true,
    smart_split = false,
    smart_resizing = true,
    force_split = 0,
    special_scale_factor = 0.8,
  },
  master = {
    new_status = "master",
    new_on_top = false,
    mfact = 0.55,
    orientation = "left",
    special_scale_factor = 0.8,
  },
  misc = {
    force_default_wallpaper = 0,
    disable_hyprland_logo = true,
    disable_splash_rendering = true,
    mouse_move_enables_dpms = true,
    key_press_enables_dpms = true,
    enable_swallow = true,
    swallow_regex = "^(ghostty|kitty|alacritty|Alacritty)$",
    swallow_exception_regex = "^(wev)$",
    focus_on_activate = true,
    animate_manual_resizes = false,
    animate_mouse_windowdragging = false,
    disable_autoreload = false,
    vrr = 2,
  },
  cursor = {
    no_hardware_cursors = false,
    no_break_fs_vrr = false,
    min_refresh_rate = 24,
    hotspot_padding = 1,
    inactive_timeout = 0,
    no_warps = false,
    persistent_warps = false,
    warp_on_change_workspace = false,
  },
})

hl.curve("easeOutQuint",   { type = "bezier", points = { {0.23, 1},    {0.32, 1}   } })
hl.curve("easeInOutCubic", { type = "bezier", points = { {0.65, 0.05}, {0.36, 1}   } })
hl.curve("linear",         { type = "bezier", points = { {0, 0},       {1, 1}      } })
hl.curve("almostLinear",   { type = "bezier", points = { {0.5, 0.5},   {0.75, 1.0} } })
hl.curve("quick",          { type = "bezier", points = { {0.15, 0},    {0.1, 1}    } })

hl.animation({ leaf = "global",           enabled = true, speed = 10,   bezier = "default" })
hl.animation({ leaf = "border",           enabled = true, speed = 5.39, bezier = "easeOutQuint" })
hl.animation({ leaf = "borderangle",      enabled = true, speed = 100,  bezier = "linear",       style = "loop" })
hl.animation({ leaf = "windows",          enabled = true, speed = 4.79, bezier = "easeOutQuint", style = "slide" })
hl.animation({ leaf = "windowsIn",        enabled = true, speed = 4.1,  bezier = "easeOutQuint", style = "popin 87%" })
hl.animation({ leaf = "windowsOut",       enabled = true, speed = 1.49, bezier = "linear",       style = "popin 87%" })
hl.animation({ leaf = "windowsMove",      enabled = true, speed = 4.79, bezier = "easeOutQuint", style = "slide" })
hl.animation({ leaf = "fadeIn",           enabled = true, speed = 1.73, bezier = "almostLinear" })
hl.animation({ leaf = "fadeOut",          enabled = true, speed = 1.46, bezier = "almostLinear" })
hl.animation({ leaf = "fade",             enabled = true, speed = 3.03, bezier = "quick" })
hl.animation({ leaf = "layers",           enabled = true, speed = 3.81, bezier = "easeOutQuint", style = "slide" })
hl.animation({ leaf = "layersIn",         enabled = true, speed = 4,    bezier = "easeOutQuint", style = "slide" })
hl.animation({ leaf = "layersOut",        enabled = true, speed = 1.5,  bezier = "linear",       style = "fade" })
hl.animation({ leaf = "fadeLayersIn",     enabled = true, speed = 1.79, bezier = "almostLinear" })
hl.animation({ leaf = "fadeLayersOut",    enabled = true, speed = 1.39, bezier = "almostLinear" })
hl.animation({ leaf = "workspaces",       enabled = true, speed = 1.94, bezier = "almostLinear", style = "slide" })
hl.animation({ leaf = "workspacesIn",     enabled = true, speed = 1.21, bezier = "almostLinear", style = "slidevert" })
hl.animation({ leaf = "workspacesOut",    enabled = true, speed = 1.94, bezier = "almostLinear", style = "slidevert" })
hl.animation({ leaf = "specialWorkspace", enabled = true, speed = 3,    bezier = "easeOutQuint", style = "slidevert" })
```

- [ ] **Step 3: input.lua**

`conf/input.lua.j2`:

```lua
-- {{ ansible_managed }}
hl.config({
  input = {
    kb_layout = "us",
    kb_variant = "",
    kb_model = "",
    kb_options = "",
    kb_rules = "",
    follow_mouse = 1,
    mouse_refocus = true,
    float_switch_override_focus = 2,
    sensitivity = 0,
    accel_profile = "adaptive",
    touchpad = {
      natural_scroll = true,
      disable_while_typing = true,
      tap_to_click = true,
      drag_lock = false,
      tap_and_drag = true,
      scroll_factor = 1.0,
      middle_button_emulation = false,
      clickfinger_behavior = false,
    },
  },
  gestures = {
    workspace_swipe_distance = 300,
    workspace_swipe_invert = false,
    workspace_swipe_min_speed_to_force = 30,
    workspace_swipe_cancel_ratio = 0.5,
    workspace_swipe_create_new = true,
    workspace_swipe_forever = true,
  },
})

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
hl.gesture({ fingers = 3, direction = "down", mods = "ALT", action = "close" })
hl.gesture({ fingers = 3, direction = "up", mods = "SUPER", scale = 1.5, action = "fullscreen" })

-- Upstream example leftover, kept verbatim from the .conf
hl.device({ name = "epic-mouse-v1", sensitivity = -0.5 })
```

Note `tap-to-click` and `tap-and-drag` become `tap_to_click` / `tap_and_drag` in Lua table keys (hyphens are not valid identifiers). If `--verify-config` reports them as unknown, check the stub's `HL.ConfigInput` touchpad fields for the exact names and use those.

- [ ] **Step 4: binds.lua**

`conf/binds.lua.j2`:

```lua
-- {{ ansible_managed }}
local mod = "SUPER"
local terminal    = "alacritty"
local fileManager = "thunar"
local menu        = "wofi --show drun --allow-images"
local browser     = "firefox"
local lock        = "hyprlock"
local logout      = "wlogout -p layer-shell"

-- Programs
hl.bind(mod .. " + T",         hl.dsp.exec_cmd(terminal))
hl.bind(mod .. " + B",         hl.dsp.exec_cmd(browser))
hl.bind(mod .. " + E",         hl.dsp.exec_cmd(fileManager))
hl.bind(mod .. " + SPACE",     hl.dsp.exec_cmd(menu))
hl.bind(mod .. " + SHIFT + V", hl.dsp.exec_cmd("cliphist list | wofi --show dmenu -H 600 -W 900 | cliphist decode | wl-copy"))

-- Window management
hl.bind(mod .. " + C",         hl.dsp.window.close())
hl.bind(mod .. " + V",         hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + F",         hl.dsp.window.fullscreen({ action = "toggle", mode = "fullscreen" }))
hl.bind(mod .. " + SHIFT + F", hl.dsp.window.fullscreen({ action = "toggle", mode = "maximized" }))
hl.bind(mod .. " + P",         hl.dsp.window.pseudo({ action = "toggle" }))   -- dwindle
hl.bind(mod .. " + J",         hl.dsp.layout("togglesplit"))                   -- dwindle
hl.bind(mod .. " + L",         hl.dsp.exec_cmd(lock))
hl.bind(mod .. " + SHIFT + L", hl.dsp.exec_cmd(logout))
hl.bind(mod .. " + M",         hl.dsp.exit())

-- Screenshots
hl.bind(mod .. " + SHIFT + S",     hl.dsp.exec_cmd("grim -g \"$(slurp)\" - | wl-copy && wl-paste | cliphist store"))
hl.bind(mod .. " + SHIFT + Print", hl.dsp.exec_cmd("grim -g \"$(slurp)\" ~/Pictures/Screenshots/$(date +%Y%m%d_%H%M%S).png"))
hl.bind("Print",                   hl.dsp.exec_cmd("grim ~/Pictures/Screenshots/$(date +%Y%m%d_%H%M%S).png"))

-- Focus: arrows and vim keys
for _, pair in ipairs({ { "left", "left" }, { "right", "right" }, { "up", "up" }, { "down", "down" },
                        { "h", "left" }, { "l", "right" }, { "k", "up" }, { "j", "down" } }) do
  hl.bind(mod .. " + " .. pair[1], hl.dsp.focus({ direction = pair[2] }))
end

-- Move window
hl.bind(mod .. " + SHIFT + left",  hl.dsp.window.move({ direction = "left" }))
hl.bind(mod .. " + SHIFT + right", hl.dsp.window.move({ direction = "right" }))
hl.bind(mod .. " + SHIFT + up",    hl.dsp.window.move({ direction = "up" }))
hl.bind(mod .. " + SHIFT + down",  hl.dsp.window.move({ direction = "down" }))

-- Resize window
hl.bind(mod .. " + CTRL + left",  hl.dsp.window.resize({ x = -20, y = 0,   relative = true }))
hl.bind(mod .. " + CTRL + right", hl.dsp.window.resize({ x = 20,  y = 0,   relative = true }))
hl.bind(mod .. " + CTRL + up",    hl.dsp.window.resize({ x = 0,   y = -20, relative = true }))
hl.bind(mod .. " + CTRL + down",  hl.dsp.window.resize({ x = 0,   y = 20,  relative = true }))

-- Workspaces 1..10 (key 0 = workspace 10)
for i = 1, 10 do
  local key = i % 10
  hl.bind(mod .. " + " .. key,                  hl.dsp.focus({ workspace = i }))
  hl.bind(mod .. " + SHIFT + " .. key,          hl.dsp.window.move({ workspace = i, follow = true }))
  hl.bind(mod .. " + CTRL + SHIFT + " .. key,   hl.dsp.window.move({ workspace = i, follow = false }))
end

-- Special workspace
hl.bind(mod .. " + S",         hl.dsp.workspace.toggle_special("magic"))
hl.bind(mod .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }))

-- Cycle workspaces
hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))
hl.bind("CTRL + left",          hl.dsp.focus({ workspace = "e-1" }))
hl.bind("CTRL + right",         hl.dsp.focus({ workspace = "e+1" }))

-- Mouse drag / resize
hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- Media and brightness (work while locked, repeat while held)
hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("wpctl set-volume -l 1.5 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),        { locked = true, repeating = true })
hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),       { locked = true, repeating = true })
hl.bind("XF86AudioMicMute",      hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),     { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl set 10%+"),                           { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl set 10%-"),                           { locked = true, repeating = true })
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })
hl.bind("XF86AudioStop",  hl.dsp.exec_cmd("playerctl stop"),       { locked = true })

-- Laptop lid
hl.bind("switch:on:Lid Switch",  hl.dsp.exec_cmd("hyprctl keyword monitor 'eDP-1, disable'"),                   { locked = true })
hl.bind("switch:off:Lid Switch", hl.dsp.exec_cmd("hyprctl keyword monitor 'eDP-1, 2256x1504@60, auto, 2'"),     { locked = true })
```

The focus loop produces 8 binds and the workspace loop 30, so the literal `hl.bind(` count is 54; the Step 1 grep accepts 50 to 69 to leave room for the implementer to unroll the focus loop if the stub rejects table literals in a loop (it won't, but the check should not be brittle).

- [ ] **Step 5: rules.lua and delete the old template**

`conf/rules.lua.j2`:

```lua
-- {{ ansible_managed }}
-- Workspace rules: no gaps or borders when a workspace holds a single tiled window
hl.workspace_rule({ workspace = "w[t1]",  gaps_out = 0, gaps_in = 0, border = false, rounding = false })
hl.workspace_rule({ workspace = "w[tg1]", gaps_out = 0, gaps_in = 0, border = false, rounding = false })
hl.workspace_rule({ workspace = "f[1]",   gaps_out = 0, gaps_in = 0, border = false, rounding = false })

-- Blur behind bar, notifications and launcher
hl.layer_rule({ match = { namespace = "waybar" },        blur = true })
hl.layer_rule({ match = { namespace = "notifications" }, blur = true })
hl.layer_rule({ match = { namespace = "wofi" },          blur = true })
```

Then `git rm roles/hyprland/templates/home/config/hypr/hyprland.conf.j2`.

- [ ] **Step 6: Run the fast loop to verify it passes**

Run: `bash /tmp/claude-render/render.sh`
Expected: `verify-lua: ok` then `content checks: ok`. If `--verify-config` names a key it does not know (most likely candidates: `touchpad.tap_to_click`, `gestures.*`, `workspace_rule.border`, `fullscreen.mode`), look the field up in `/usr/share/hypr/stubs/hl.meta.lua` (`podman run --rm ghcr.io/danmwallace/atomic-hyprland:44 grep -n '<name>' /usr/share/hypr/stubs/hl.meta.lua`) and use the documented name. Record each such rename in the commit body.

- [ ] **Step 7: Review Focus 1, error isolation**

Run:
```bash
cp -r /tmp/claude-render/hypr /tmp/claude-render/broken
echo 'hl.bind("SUPER + Z", hl.dsp.nonexistent())' >> /tmp/claude-render/broken/conf/binds.lua
~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora/roles/hyprland/molecule/verify-lua.sh /tmp/claude-render/broken; echo "exit=$?"
```
Expected: `verify-lua: FAILED`, exit 1, and the tail shows the error pointing at `conf/binds.lua` while the earlier `DEBUG`-stripped lines show no error for the other modules. This proves the failure is scoped; it is the manual check behind Review Focus 1 (the automated version is Task 6's smoke test).

- [ ] **Step 8: Lint and commit**

```bash
cd ~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora
ansible-lint
git add -A roles/hyprland/templates
git commit -m "feat(hyprland): port look, input, binds and rules to Lua; drop hyprland.conf.j2

Trimmed per the design: browser is firefox; tailscale, Flatpak and xhost
autostart lines removed; duplicate layer rules and commented window rules gone.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 4: Nerd Font task, hyprland-guiutils, Waybar updates module

**Files:**
- Modify: `roles/hyprland/defaults/main.yml`
- Modify: `roles/hyprland/tasks/main.yml`
- Modify: `roles/hyprland/handlers/main.yml`
- Modify: `roles/hyprland/templates/home/config/waybar/config.j2`
- Modify: `roles/hyprland/molecule/skel/verify.yml`, `roles/hyprland/molecule/default/verify.yml`

**Interfaces:**
- Produces variables `hyprland_nerd_font_url`, `hyprland_nerd_font_checksum`, `hyprland_nerd_font_dir`; file `{{ hyprland_nerd_font_dir }}/RobotoMonoNerdFontPropo-Regular.ttf`; handler `Refresh font cache`.

- [ ] **Step 1: Write the failing verify assertions**

Append to both scenarios' `verify.yml` task lists:

```yaml
    - name: Stat the Nerd Font and guiutils
      ansible.builtin.stat:
        path: /usr/share/fonts/roboto-mono-nerd/RobotoMonoNerdFontPropo-Regular.ttf
      register: hyprland_font_file

    - name: Assert the Nerd Font is installed
      ansible.builtin.assert:
        that: hyprland_font_file.stat.exists

    - name: Resolve the family name the configs use
      ansible.builtin.command: fc-match -f '%{family}' RobotoMonoNerdFontPropo
      changed_when: false
      register: hyprland_font_match

    - name: Assert fontconfig resolves RobotoMonoNerdFontPropo to the Nerd Font
      ansible.builtin.assert:
        that: "'Nerd Font Propo' in hyprland_font_match.stdout"

    - name: Check hyprland-guiutils is installed
      ansible.builtin.command: rpm -q hyprland-guiutils
      changed_when: false

    - name: Read the rendered Waybar config
      ansible.builtin.slurp:
        src: "{{ '/etc/skel' if hyprland_verify_skel | default(false) else '/home/hyprtest' }}/.config/waybar/config"
      register: hyprland_waybar_config

    - name: Assert the dnf-based updates module is gone
      ansible.builtin.assert:
        that: "'custom/updates' not in (hyprland_waybar_config.content | b64decode)"
```

In `skel/verify.yml` set `vars: { hyprland_verify_skel: true }` on the play.

- [ ] **Step 2: Run the skel scenario to verify it fails**

Run: `cd roles/hyprland && molecule test -s skel 2>&1 | tail -30`
Expected: converge passes (Tasks 2 and 3 are in), verify fails at "Assert the Nerd Font is installed".

- [ ] **Step 3: Defaults, tasks, handler**

Append to `defaults/main.yml`:

```yaml

# Nerd Font the Waybar, Wofi and hyprlock templates reference as
# RobotoMonoNerdFontPropo. Pinned upstream release; bump both values together.
hyprland_nerd_font_url: "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/RobotoMono.tar.xz"
hyprland_nerd_font_checksum: "sha256:61f53438b240a00c87c92dc2c372db0bbb264473b36a8144ea62babf787f8383"
hyprland_nerd_font_dir: /usr/share/fonts/roboto-mono-nerd
```

In `tasks/main.yml`, add `hyprland-guiutils` to the package list right after `hyprland`, and add after the package task:

```yaml
- name: "Check whether the Nerd Font is already installed"
  ansible.builtin.stat:
    path: "{{ hyprland_nerd_font_dir }}/RobotoMonoNerdFontPropo-Regular.ttf"
  register: hyprland_nerd_font_marker

- name: "Ensure the Nerd Font archive is downloaded"
  ansible.builtin.get_url:
    url: "{{ hyprland_nerd_font_url }}"
    dest: /tmp/hyprland-nerd-font.tar.xz
    checksum: "{{ hyprland_nerd_font_checksum }}"
    mode: "0644"
  when: not hyprland_nerd_font_marker.stat.exists

- name: "Ensure the Nerd Font directory exists"
  ansible.builtin.file:
    path: "{{ hyprland_nerd_font_dir }}"
    state: directory
    mode: "0755"
  become: true

- name: "Ensure the Nerd Font is installed"
  ansible.builtin.unarchive:
    src: /tmp/hyprland-nerd-font.tar.xz
    dest: "{{ hyprland_nerd_font_dir }}"
    remote_src: true
    creates: "{{ hyprland_nerd_font_dir }}/RobotoMonoNerdFontPropo-Regular.ttf"
    mode: "0644"
  become: true
  when: not hyprland_nerd_font_marker.stat.exists
  notify: Refresh font cache

- name: "Ensure the Nerd Font archive is removed after install"
  ansible.builtin.file:
    path: /tmp/hyprland-nerd-font.tar.xz
    state: absent
  when: not hyprland_nerd_font_marker.stat.exists
```

`handlers/main.yml`:

```yaml
# SPDX-License-Identifier: MIT
---
# handlers file for hyprland

- name: Refresh font cache
  ansible.builtin.command: fc-cache -f
  become: true
  changed_when: true
```

Why the marker stat: `get_url` with a checksum re-downloads nothing when the file exists, but the archive is deleted after install, so without the guard every run would download 4 MB. The second run sees the marker and skips all four tasks: idempotent.

In `templates/home/config/waybar/config.j2`: remove `"custom/updates"` from the `modules-left` array and delete the whole `"custom/updates": { ... },` block (8 lines, from `"custom/updates": {` to the closing `},`).

- [ ] **Step 4: Run the skel scenario to verify it passes, including idempotence**

Run: `molecule test -s skel 2>&1 | grep -E 'Executed|failed=|changed='`
Expected: converge `changed>0`, idempotence `changed=0`, verify successful.

- [ ] **Step 5: Run the default scenario and lint**

Run: `molecule test -s default 2>&1 | grep -E 'Executed|failed='; cd ../.. && ansible-lint`
Expected: all phases successful; lint `Passed`.

- [ ] **Step 6: Commit**

```bash
git add roles/hyprland
git commit -m "feat(hyprland): install RobotoMono Nerd Font, add guiutils, drop Waybar updates module

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 5: Release danmwallace.fedora 1.2.0

**Files:**
- Modify: `galaxy.yml` (`1.1.2` to `1.2.0`), `CHANGELOG.md`, `README.md`, `roles/hyprland/README.md`, `roles/hyprland/meta/argument_specs.yml`

- [ ] **Step 1: argument_specs**

Append to `options:`:

```yaml
      hyprland_nerd_font_url:
        description:
          - Upstream tarball of the RobotoMono Nerd Font the templates reference.
        type: str
        required: false
        default: "https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/RobotoMono.tar.xz"
      hyprland_nerd_font_checksum:
        description:
          - Checksum for hyprland_nerd_font_url in get_url format (algorithm:hex).
        type: str
        required: false
        default: "sha256:61f53438b240a00c87c92dc2c372db0bbb264473b36a8144ea62babf787f8383"
      hyprland_nerd_font_dir:
        description:
          - Directory the font files are extracted into.
        type: str
        required: false
        default: /usr/share/fonts/roboto-mono-nerd
```

- [ ] **Step 2: CHANGELOG**

Insert above `## [1.1.2]`:

```markdown
## [1.2.0] - 2026-10-04

### Changed

- The Hyprland configuration is rendered as Lua (`hyprland.lua` plus
  `conf/*.lua` modules) instead of `hyprland.conf`. Hyprland 0.57 removes the
  `.conf` format; 0.56 already prefers the Lua file when both exist. Existing
  `hyprland.conf` and `local.conf` files are left in place and ignored.
- Per-machine overrides live in `~/.config/hypr/local.lua` (created once, never
  overwritten). Move anything from `local.conf` there by hand.
- Trimmed from the shipped config: the browser bind now launches `firefox`;
  autostart no longer runs tailscale, the KTailctl and Vesktop Flatpaks or
  `xhost`; duplicate layer rules and commented window rules are gone.

### Added

- RobotoMono Nerd Font (pinned upstream release, checksum-verified) installed to
  `/usr/share/fonts/roboto-mono-nerd`; variables `hyprland_nerd_font_url`,
  `hyprland_nerd_font_checksum`, `hyprland_nerd_font_dir`. The Waybar, Wofi and
  hyprlock templates already reference it.
- `hyprland-guiutils` (runtime dependency for Hyprland dialogs).
- Molecule verifies the rendered tree with `Hyprland --verify-config`.

### Removed

- `hyprland.conf.j2` and the `local.conf` task.
- Waybar `custom/updates` module (openSUSE leftover running `checkupdates` and
  `zypper dup`).
```

- [ ] **Step 3: READMEs**

`roles/hyprland/README.md`: in the intro replace "a themed set of user dotfiles" with "a themed set of user dotfiles (Hyprland's Lua config split into `conf/*.lua` modules)". Add the three font variables to the table. Replace the Testing section's bullet for `skel` with "`skel`: a plain container mirroring an image build; both scenarios run `molecule/verify-lua.sh`, which parses the rendered tree with `Hyprland --verify-config`." Add a short section:

```markdown
## Per-machine overrides

`~/.config/hypr/local.lua` is created once and never touched again. It is loaded
last via `pcall(require, "local")`, so it can override anything. Example for a
VM with a virtual display:

```lua
hl.monitor({ output = "Virtual-1", mode = "preferred", position = "auto", scale = 1 })
hl.config({ cursor = { no_hardware_cursors = true } })
hl.env("WLR_RENDERER_ALLOW_SOFTWARE", "1")
```
```

Collection `README.md`: change "installs and themes Hyprland" wording to mention the Lua config if it names the format; otherwise no change.

- [ ] **Step 4: Bump, lint, PR, merge, tag**

```bash
sed -i 's/^version: 1.1.2$/version: 1.2.0/' galaxy.yml
ansible-lint
git add galaxy.yml CHANGELOG.md README.md roles/hyprland/README.md roles/hyprland/meta/argument_specs.yml
git commit -m "chore: release v1.2.0 — Lua config, Nerd Font, guiutils

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/lua-config
gh pr create --title "feat(hyprland): Lua config port, Nerd Font, guiutils (v1.2.0)" --body "..."
# wait for CI (ansible-lint, build-collection, release-tag audit), then:
gh pr merge --squash --delete-branch
git switch main && git pull
git tag -a v1.2.0 -m "v1.2.0" && git push origin v1.2.0
```

Expected: Release workflow publishes 1.2.0 (`gh run list --workflow Release --limit 1` shows success).

---

### Task 6: Image: sync-dotfiles to local.lua, smoke test for the Lua tree

**Files (in `~/Code/atomic-hyprland`):**
- Modify: `tests/test-sync-dotfiles.sh`
- Modify: `tests/image-smoke.sh`
- Modify: `files/usr/libexec/atomic-hyprland/sync-dotfiles`
- Modify: `build/40-finalize.sh` (manifest exclusion)

**Interfaces:**
- Consumes `/usr/share/atomic-hyprland/{stamp,skel,managed-files.txt}`.
- Produces: `local.lua` excluded from the manifest and created once by the sync.

- [ ] **Step 1: Write the failing tests**

In `tests/test-sync-dotfiles.sh`: replace every `.config/hypr/local.conf` with `.config/hypr/local.lua`, change the sentinel write in case 2 to `printf 'hl.env("SENTINEL", "1")\n' > "$HOME/.config/hypr/local.lua"` and the case-5 sentinel to `printf 'hl.env("SENTINEL", "1")\n'`, and add before case 6:

```bash
# 5b. a home still holding the old .conf files: untouched, local.lua still created
export HOME="$(mktemp -d)"
mkdir -p "$HOME/.config/hypr"
echo "# old" > "$HOME/.config/hypr/hyprland.conf"
echo "# old" > "$HOME/.config/hypr/local.conf"
"${sync}"
expect "old hyprland.conf left in place" 'grep -q "^# old" "$HOME/.config/hypr/hyprland.conf"'
expect "old local.conf left in place" 'grep -q "^# old" "$HOME/.config/hypr/local.conf"'
expect "local.lua created beside the old files" 'test -f "$HOME/.config/hypr/local.lua"'
expect "hyprland.lua synced" 'test -f "$HOME/.config/hypr/hyprland.lua"'
```

In `tests/image-smoke.sh` replace the Hyprland verify block and the `local.conf` checks with:

```bash
check test -f /etc/skel/.config/hypr/hyprland.lua
check test -f /etc/skel/.config/hypr/conf/binds.lua
check test -f /etc/skel/.config/hypr/local.lua
check bash -c '! test -e /etc/skel/.config/hypr/hyprland.conf'
check bash -c '! test -e /etc/skel/.config/hypr/local.conf'
check grep -q 'pcall(require, "local")' /etc/skel/.config/hypr/hyprland.lua
# Hyprland's own parser on the skel tree, without --config so its file selection picks hyprland.lua.
verify_hypr() {
    export HOME=/tmp/hv XDG_RUNTIME_DIR=/tmp/hv/run
    rm -rf /tmp/hv; mkdir -p "$HOME/.config" "$XDG_RUNTIME_DIR"
    cp -r /etc/skel/.config/hypr "$HOME/.config/"
    [ -n "${1:-}" ] && echo "$1" >> "$HOME/.config/hypr/conf/binds.lua"
    Hyprland --verify-config --i-am-really-stupid 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
}
out="$(verify_hypr)"
check bash -c "echo '$out' | grep -q 'config ok'"
check bash -c "! echo '$out' | grep -Eq 'attempt to|stack traceback|Config error'"
check bash -c "echo '$out' | grep -q 'Using lua config'"
# Error isolation: a broken binds.lua must be reported by name while the entry file still loads.
out="$(verify_hypr 'hl.bind("SUPER + Z", hl.dsp.nonexistent())')"
check bash -c "echo '$out' | grep -q 'binds.lua'"
check bash -c "! echo '$out' | grep -q 'hyprland.lua:'"
check rpm -q hyprland-guiutils
check bash -c "fc-match -f '%{family}' RobotoMonoNerdFontPropo | grep -q 'Nerd Font Propo'"
check bash -c '! grep -q "custom/updates" /etc/skel/.config/waybar/config'
```

Quoting note: `$out` is embedded in a double-quoted `bash -c` string; the Hyprland output contains no single quotes in practice, but to be safe write the two helpers as `check_contains() { grep -q "$2" <<< "$1"; }` and call `check check_contains "$out" 'config ok'` instead of inlining. Use that form.

- [ ] **Step 2: Run both to verify they fail**

Run: `just test 2>&1 | grep -E 'FAIL|exit'`
Expected: `hyprland.lua` checks FAIL (the current image still ships the .conf tree); the sync test's `local.lua` cases FAIL.

- [ ] **Step 3: Sync script and manifest**

In `files/usr/libexec/atomic-hyprland/sync-dotfiles` change `local_conf=.config/hypr/local.conf` to `local_conf=.config/hypr/local.lua` and the comment to "never got skel's local.lua, yet hyprland.lua requires it". In `build/40-finalize.sh` change the manifest exclusion to `! -path '.config/hypr/local.lua'` and remove the mention of local.conf in the comment.

- [ ] **Step 4: Commit (tests go green in Task 7's build)**

```bash
cd ~/Code/atomic-hyprland
git add tests files/usr/libexec/atomic-hyprland/sync-dotfiles build/40-finalize.sh
git commit -m "feat: sync and verify the Lua Hyprland config; local.lua is the override

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 7: Image: pin role 1.2.0, drop the 0.56 pin, build, test, push

**Files:**
- Modify: `build/requirements.yml` (`v1.1.2` to `v1.2.0`)
- Modify: `build/packages.txt` (remove the `hyprland-0.56*` line and its comment)
- Modify: `tests/image-smoke.sh` (remove the 0.56 version check from Task 1)
- Modify: `README.md` (local.lua example in the VM runbook)

- [ ] **Step 1: Edit, build, test**

```bash
cd ~/Code/atomic-hyprland
sed -i 's/version: v1.1.2/version: v1.2.0/' build/requirements.yml
# remove the two transitional lines from build/packages.txt and the VERSION check from tests/image-smoke.sh
just check-kernel && just build 2>&1 | tail -5 && just test
```
Expected: build succeeds with `bootc container lint` passing; `just test` prints only `ok` lines for both suites and exits 0.

- [ ] **Step 2: README**

In `README.md`'s VM runbook replace the sentence about `local.conf` with:

```markdown
The VM's `~/.config/hypr/local.lua` carries the virtual-monitor and software
rendering settings; it is never managed by the image:

```lua
hl.monitor({ output = "Virtual-1", mode = "preferred", position = "auto", scale = 1 })
hl.config({ cursor = { no_hardware_cursors = true } })
hl.env("WLR_RENDERER_ALLOW_SOFTWARE", "1")
```
```

- [ ] **Step 3: Push image and commit**

```bash
just push
skopeo inspect --no-creds docker://ghcr.io/danmwallace/atomic-hyprland:44 | jq -r '.Labels["org.opencontainers.image.version"]'
git add build/requirements.yml build/packages.txt tests/image-smoke.sh README.md
git commit -m "feat: ship role v1.2.0 (Lua config, Nerd Font); drop the 0.56 pin

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/lua-port
```

---

### Task 8: VM upgrade and acceptance

**Files:** none in git (vault task updates only).

- [ ] **Step 1: Announce, upgrade, reboot**

Tell Dan the VM will reboot. Then:

```bash
ssh dwallace@192.168.70.14 bash -c "'sudo bootc upgrade 2>&1 | tail -3; sudo systemctl reboot'"
until ssh -o ConnectTimeout=5 -o BatchMode=yes dwallace@192.168.70.14 true 2>/dev/null; do sleep 5; done
```

- [ ] **Step 2: Write local.lua and verify over SSH**

```bash
ssh dwallace@192.168.70.14 bash -s <<'EOF'
cat > ~/.config/hypr/local.lua <<'LUA'
-- VM: virtio-gpu, software rendering
hl.monitor({ output = "Virtual-1", mode = "preferred", position = "auto", scale = 1 })
hl.config({ cursor = { no_hardware_cursors = true } })
hl.env("WLR_RENDERER_ALLOW_SOFTWARE", "1")
LUA
sudo bootc status --format json | jq -r '.status.booted.image.version'
journalctl --user -u atomic-hyprland-dotfiles -o cat --no-pager | tail -1
ls ~/.config/hypr ~/.config/hypr/conf
export XDG_RUNTIME_DIR=/run/user/$(id -u); Hyprland --verify-config 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E 'Using lua|config ok|attempt to|Config error'
fc-match -f '%{family}\n' RobotoMonoNerdFontPropo
EOF
```
Expected: new version; `synced to <version>`; `hyprland.lua`, `local.lua`, old `hyprland.conf` and `local.conf` still listed, `conf/` has the seven modules; `Using lua config` and `config ok`, no errors; `RobotoMono Nerd Font Propo`.

- [ ] **Step 3: Dan's graphical acceptance**

Ask Dan to log in at `virt-viewer -c qemu+ssh://dwallace@10.10.99.4/system hypr-test` and confirm: no notification banners, Waybar icons render, Super+T, Super+Space, Super+C, Super+arrows, Super+1..5, Super+L work, and the two mouse binds (Super+left-drag moves a window, Super+right-drag resizes it; their `mouse` flag is the one thing `--verify-config` cannot see). Record the outcome in the vault task "Confirm Graphical Login on hypr-test" (mark Done) and add a note to `Projects/Atomic Hyprland/Project Overview.md` Current Focus.

- [ ] **Step 4: Finish the branch**

Use the finishing-a-development-branch flow for `dw/lua-port` (Dan chose local merge last time; ask again).

---

## Self-review notes

- Spec coverage: layout and entry (T2), mapping table (T2, T3), trim list (T2 autostart, T3 binds/rules), font/guiutils/Waybar (T4), release 1.2.0 (T5), sync + smoke test (T6), image pin removal and build (T1, T7), VM rollout and acceptance (T8). Rollback is `bootc rollback` (no task needed).
- Names used consistently: `verify-lua.sh`, `palette`, `conf.<module>`, `local.lua`, `hyprland_nerd_font_{url,checksum,dir}`, handler `Refresh font cache`.
- Open risk named in the spec (two dispatcher argument shapes) is resolved from the wiki's dispatcher table: `resize({ x, y, relative = true })`, `fullscreen({ action, mode })`, `move({ workspace, follow })`. Step 6 of Task 3 says what to do if the stub disagrees.
