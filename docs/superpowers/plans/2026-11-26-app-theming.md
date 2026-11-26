# Apps Follow the Desktop Theme: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After `hypr-theme set <name>`, Helix, Chromium (through GTK) and Vesktop take on that theme, using existing themes. Helix also gets its themes and syntax highlighting back.

**Architecture:** each shipped theme gains an `apps.toml` naming its Helix theme and its Vesktop theme. Two new shipped hooks in `hooks/theme-set.d/` apply them on every switch and at login. GTK moves from Adwaita-dark to `adw-gtk3-dark`, with a widened `gtk.css` that sets libadwaita's named colors from `colors.toml`. Chromium in GTK mode follows GTK.

**Tech stack:** bash (hooks, `hypr-theme`), Fedora packages (`helix-themes`, `helix-parsers`, `adw-gtk3-theme`), the GTK/libadwaita named-color CSS, and Vencord local themes.

**Spec:** `docs/superpowers/specs/2026-11-26-app-theming-design.md` (approved 2026-11-26).

## Global constraints

- **Only image-owned files are written:**
  - Helix: `~/.config/helix/themes/atomic-hyprland.toml`, never `config.toml`.
  - Vesktop: `…/vesktop/themes/atomic-hyprland.css`, never `settings.json` or Quick CSS.
- **Hooks never restart an app,** never fail a theme switch, and exit 0 when their app isn't installed or has no mapping.
- **Every Vesktop theme URL is pinned** to a tag or commit (for example `cdn.jsdelivr.net/gh/<owner>/<repo>@<tag-or-sha>/<file>`), never a branch.
- **New packages go in `build/packages.txt`.** No new downloads in the Containerfile.
- **Obsidian is out of scope.**
- **Shell style:** `#!/usr/bin/bash`, `set -euo pipefail`, 4-space indent. Tests use the existing `check` pattern and are wired into `just test`.
- **The Flatpak override** in `hypr-theme` keeps `GTK_THEME=Adwaita:dark`. The `adw-gtk3-dark` Flatpak extension is an Ansible follow-up (spec section 3), so the image doesn't change Flatpak GTK3 apps yet.

## Review focus

1. **A user theme without `apps.toml`:** Helix gets `base16_terminal`, Vesktop's file is removed or left empty, and the switch succeeds. Tested in Tasks 4 and 7.
2. **The app isn't installed** (no `hx`, no Vesktop config folder): the hook is a silent no-op, exit 0. Tested in Tasks 4 and 7.
3. **Bad `apps.toml` values:** a Helix name with `/`, `..` or spaces, or a Vesktop URL that isn't `https://` or is unpinned (`@main`, `@master`, `/refs/heads/`). The hook refuses that value, falls back as in 1, and exits 0. Tested in Tasks 4 and 7.
4. **Readability:** every theme's GTK foreground on its window, view and headerbar backgrounds keeps a contrast ratio of at least 4.5:1. Tested in Task 5.
5. **No running `hx`:** the reload signal doesn't fail the hook. Tested in Task 4.

---

### Task 1: Verify early (on frmwrk; reversible; Dan-assisted where marked)

**Files:**
- Modify: this plan's "Findings" section at the end (the results, which later tasks read).

**Interfaces:**
- Produces, for later tasks:
  - whether `SIGUSR1` reloads Helix's theme;
  - whether GTK and Chromium need the "nudge";
  - whether Chromium's GTK mode can be set in `master_preferences`, and with which key;
  - whether Vencord reloads local themes live and allows remote `@import`;
  - the pinned Vesktop URL table, and Midnight's accent variable names.

- [ ] **Step 1: Helix.** In a scratch folder:
  1. Extract `helix-themes` and `helix-parsers` (`dnf download` from Fedora's repo, then `rpm2cpio | cpio -id`) into `~/.config/helix/runtime/`. That's the user runtime folder Helix searches first, and it's reversible.
  2. Write `~/.config/helix/themes/atomic-hyprland.toml` with `inherits = "tokyonight"`, start `hx` with `theme = "atomic-hyprland"` in a temporary config (`hx -c <file>`), then change `inherits` to `nord` and send `pkill -USR1 -x hx`.

  Record: did the open editor switch theme? Did highlighting appear (`hx --health rust` shows highlights ✓)? Then remove `~/.config/helix/runtime` and the test theme file.

- [ ] **Step 2: GTK and Chromium (Dan-assisted: he judges the look).**
  1. Extract `adw-gtk3-theme` into `~/.local/share/themes/`.
  2. Run `gsettings set org.gnome.desktop.interface gtk-theme adw-gtk3-dark`.
  3. Append the named colors from Task 5's mapping to the rendered `~/.config/atomic-hyprland/current/theme/gtk.css` for the current theme.
  4. Ask Dan to set Chromium to Appearance → GTK and compare it with a GTK3 app (`gtk3-demo`, if present, or Nautilus) and a GTK4 app.
  5. Switch themes (`hypr-theme set nord`, which re-renders `gtk.css` without the extra colors). Re-append the colors, then check whether running apps update with no nudge, after a nudge (`gsettings set … gtk-theme Adwaita-dark && gsettings set … gtk-theme adw-gtk3-dark`), or only after a restart.

  Record which applies. Then restore `gtk-theme` to `Adwaita-dark`, delete `~/.local/share/themes/adw-gtk3*`, and run `hypr-theme set <original>`.

- [ ] **Step 3: Chromium's `master_preferences` key.** Find the preference that selects GTK mode for a new profile: check Chromium's `chrome/common/pref_names.h` for `extensions.theme.system_theme` and its value for GTK. Test it with a throwaway profile: `chromium-browser --user-data-dir=$(mktemp -d) --initial-preferences-file=<file>`, if that flag exists in Chromium 157. If not, set `CHROMIUM_FLAGS` the same way. Record the key and value, or "not settable". In the second case Task 6 skips the `master_preferences` step and only documents the one-time toggle.

- [ ] **Step 4: Vesktop (Dan-assisted: he has Vesktop open).**
  1. Write `~/.var/app/dev.vencord.Vesktop/config/vesktop/themes/atomic-hyprland.css` containing `@import url("<a pinned theme URL>");`, and ask Dan to enable it under Settings → Themes.
  2. Change the `@import` to another theme's URL. Record whether it applies live, and whether the remote `@import` loads at all.
  3. If it doesn't load, test a downloaded copy of the theme's CSS in the same file. That's the fallback mode: Task 7 then fetches each pinned CSS at build time into the image (`/usr/share/atomic-hyprland/vesktop/<name>.css`), and the hook copies it instead of `@import`ing it.

  Remove the test file afterwards (Dan disables the entry).

- [ ] **Step 5: Pinned Vesktop URLs.** For each mapped theme, find the official port's Vencord/BetterDiscord CSS and a tag or commit to pin:
  - catppuccin (mocha), dracula, everforest, gruvbox, kanagawa, nord, rosé pine, tokyo night;
  - Midnight (refact0r), for the monochrome themes and neon-night.

  Record each URL and Midnight's accent CSS variable name or names in "Findings".

- [ ] **Step 6: Commit the findings.**
```bash
git add docs/superpowers/plans/2026-11-26-app-theming.md
git commit -m "docs(plan): app theming verify-early findings"
```

### Task 2: Packages: Helix themes and parsers, adw-gtk3

**Files:**
- Modify: `build/packages.txt` (after `helix`, line 141)
- Test: `tests/image-smoke.sh`

**Interfaces:**
- Produces: `/usr/lib64/helix/runtime/themes/*.toml`, `/usr/lib64/helix/runtime/queries/`, and `/usr/share/themes/adw-gtk3-dark` in the image.

- [ ] **Step 1: Write the failing smoke checks** in `tests/image-smoke.sh`, next to the existing GTK check (line 46):
```bash
check rpm -q helix-themes helix-parsers adw-gtk3-theme
check test -f /usr/lib64/helix/runtime/themes/base16_terminal.toml
check test -f /usr/lib64/helix/runtime/queries/rust/highlights.scm
check test -f /usr/share/themes/adw-gtk3-dark/gtk-3.0/gtk.css
```
- [ ] **Step 2: Run `bash -n tests/image-smoke.sh`** (smoke checks run in CI against the built image).
  Expected: no syntax error. The checks themselves fail in the PR build until Step 3.
- [ ] **Step 3: Add the packages:** `helix-themes` and `helix-parsers` under `helix`, and `adw-gtk3-theme` in the "Look" section next to the other GTK theming packages.
- [ ] **Step 4: Run `just test`.**
  Expected: passes. Package checks on the host side aren't affected.
- [ ] **Step 5: Commit.** `feat(image): Helix themes and highlighting, adw-gtk3 (Fedora packages)`

### Task 3: `apps.toml` in every shipped theme

**Files:**
- Create: `files/usr/share/atomic-hyprland/themes/<each of 17>/apps.toml`
- Modify: `tests/test-themes.sh`

**Interfaces:**
- Produces: `apps.toml` with exactly two keys, `helix = "<helix theme name>"` and `vesktop = "<pinned https URL or empty>"`. It's copied into `~/.config/atomic-hyprland/current/theme/apps.toml` by `build_next`'s existing `cp -a`.

- [ ] **Step 1: Write the failing checks** in `tests/test-themes.sh`, inside the per-theme loop:
```bash
a="$share/themes/$t/apps.toml"
check test -f "$a"
check bash -c "diff <(grep -oE '^[a-z_]+' '$a' | sort) <(printf 'helix\nvesktop\n')"
check grep -qE '^helix = "[a-z0-9_]+"$' "$a"
check grep -qE '^vesktop = "https://[^"]+@[0-9a-f.v][^"/]*/[^"]+"$' "$a"   # pinned @tag-or-sha
check bash -c "! grep -qE '@(main|master)/|/refs/heads/' '$a'"
```
  Also add the exact mapping as asserts for 3 themes:
  - `tokyo-night` → `helix = "tokyonight"`;
  - `catppuccin-mocha` → `helix = "catppuccin_mocha"`;
  - `monochrome-red` → `helix = "base16_terminal"`.
- [ ] **Step 2: Run `bash tests/test-themes.sh`.**
  Expected: FAIL (no `apps.toml`).
- [ ] **Step 3: Create the 17 files.**
  - Helix names from the spec's table (section 2).
  - Vesktop URLs from Task 1's Findings.
  - Every `monochrome-*` theme and `neon-night`: `helix = "base16_terminal"` and the Midnight URL.
- [ ] **Step 4: Run `bash tests/test-themes.sh`.**
  Expected: all `ok`.
- [ ] **Step 5: Commit.** `feat(themes): map each theme to its Helix and Vesktop counterparts`

### Task 4: Helix hook and skel config

**Files:**
- Create: `files/usr/share/atomic-hyprland/hooks/theme-set.d/40-helix`
- Create: `files/usr/share/atomic-hyprland/skel/.config/helix/config.toml` (contains `theme = "atomic-hyprland"`)
- Modify: `files/usr/share/atomic-hyprland/skel.local` (add `.config/helix/config.toml`)
- Create: `tests/test-helix-hook.sh` (wired into `justfile`'s `test` recipe)
- Modify: `tests/image-smoke.sh`

**Interfaces:**
- Consumes: `${state}/current/theme/apps.toml` (Task 3) and `HYPR_THEME_STATE` (the same variable the OpenRGB hook uses).
- Produces: `~/.config/helix/themes/atomic-hyprland.toml`, containing exactly `inherits = "<name>"`.

- [ ] **Step 1: Write the failing test.** Model it on `tests/test-openrgb-hook.sh`: a temp HOME and state with a rendered `current/theme/apps.toml`, and a stub dir holding `pkill` and `hx` stubs that log. Cases:
  - **mapped:** `apps.toml` with `helix = "tokyonight"` → the theme file contains exactly `inherits = "tokyonight"`, and the `pkill` log shows `-USR1` with `-x hx`.
  - **no `apps.toml`:** → `inherits = "base16_terminal"`; exit 0.
  - **bad value** (`helix = "../../etc"`, `helix = "a b"`) → `base16_terminal`; exit 0.
  - **no `hx` on PATH** → no file is written; exit 0.
  - **no running `hx`** (the `pkill` stub exits 1) → exit 0, and the file is still written.
  - **the user's config is never touched:** a pre-existing `~/.config/helix/config.toml` is byte-identical after the hook.
- [ ] **Step 2: Run `bash tests/test-helix-hook.sh`.**
  Expected: FAIL (no hook).
- [ ] **Step 3: Implement `40-helix`.**
  - Read `helix` from `apps.toml` with `sed`, as the OpenRGB hook reads `colors.toml`.
  - Validate it against `^[a-z0-9_]+$`, falling back to `base16_terminal`.
  - Write the file atomically (to a temp file, then `mv`).
  - `pkill -USR1 -u "$(id -u)" -x hx || true`.

  The SIGUSR1 behavior is per Task 1 Step 1. If Helix doesn't reload the theme on it, keep the signal (it still reloads the config) and note in the README that open editors pick up the theme with `:config-reload`.
- [ ] **Step 4: Add the skel file and the `skel.local` line.** Add a smoke check that every mapped `helix` value resolves:
```bash
for a in /usr/share/atomic-hyprland/themes/*/apps.toml; do n=$(sed -nE 's/^helix = "(.*)"$/\1/p' "$a"); check test -f "/usr/lib64/helix/runtime/themes/$n.toml"; done
```
- [ ] **Step 5: Run `bash tests/test-helix-hook.sh && just test`.**
  Expected: all pass.
- [ ] **Step 6: Commit.** `feat(theme): Helix follows the desktop theme (hook 40-helix)`

### Task 5: GTK through adw-gtk3, with libadwaita named colors

**Files:**
- Modify: `files/usr/share/atomic-hyprland/themed/gtk.css.tpl`
- Modify: `files/usr/bin/hypr-theme`, `apply_settings` (line ~220: `gtk-theme` becomes `adw-gtk3-dark`, plus the nudge per Task 1)
- Modify: `tests/test-themes.sh`, `tests/test-hypr-theme.sh`
- Modify: `tests/image-smoke.sh` (lines 46–48: the Adwaita-dark asset checks stay, since the Flatpak override still uses it)

**Interfaces:**
- Consumes: `colors.toml` keys only. No new keys.
- Produces: a rendered `gtk.css` defining, in this order:
  - `window_bg_color`={{ background }}, `window_fg_color`={{ foreground }};
  - `view_bg_color`={{ background_alt }}, `view_fg_color`={{ foreground }};
  - `headerbar_bg_color`={{ background_alt }}, `headerbar_fg_color`={{ foreground }};
  - `card_bg_color`={{ surface }}, `popover_bg_color`={{ background_alt }}, `sidebar_bg_color`={{ background_alt }};
  - the existing three accent colors unchanged.

  *(Mapping is my call. Tune it only if Task 1 Step 2 showed a problem.)*

- [ ] **Step 1: Write the failing checks.**
  - **`test-themes.sh`:** for every theme, the rendered `gtk.css` defines all 11 colors above, and each has a `#rrggbb` value.
  - **Contrast:** a small Python helper in the test computes the WCAG contrast of `foreground` against `background`, `background_alt` and `surface` from `colors.toml`, and requires at least 4.5 for every theme (Review focus 4).
  - **`test-hypr-theme.sh`:** in the existing stubbed-`gsettings` apply test, the log shows `gtk-theme adw-gtk3-dark`, and never `gtk-theme Adwaita-dark` as the final value. Extend the stub to log its arguments.
- [ ] **Step 2: Run `bash tests/test-themes.sh; bash tests/test-hypr-theme.sh`.**
  Expected: FAIL on the new checks.
- [ ] **Step 3: Implement.**
  - Widen the template, and update its header comment: GTK3 now uses adw-gtk3, so both GTK versions read these colors.
  - In `apply_settings`, set `gtk-theme` to `adw-gtk3-dark`. If Task 1 found the nudge necessary, set `Adwaita-dark` first and then `adw-gtk3-dark`, both `|| true`.
  - If a theme fails the contrast check, record a `Ruling:` in the ledger and adjust that theme's mapping in the template only if every theme can share it. Otherwise report the theme instead of changing its colors.
- [ ] **Step 4: Run `just test`.**
  Expected: passes.
- [ ] **Step 5: Commit.** `feat(theme): GTK3 and GTK4 take the theme's colours (adw-gtk3 + named colours)`

### Task 6: Chromium follows GTK

**Files:**
- Modify: `files/etc/chromium/policies/managed/10-atomic-hyprland.json` (remove `BrowserThemeColor`)
- Modify: `tests/test-skel-includes.sh` (line ~149: its policy assertion)
- Modify, only if Task 1 Step 3 found a key: the build step that patches `/etc/chromium/master_preferences` with `jq`, keeping Fedora's keys (in `build/20-desktop.sh`); and `tests/image-smoke.sh`

**Interfaces:**
- Consumes: Task 5 (GTK follows the theme). Task 1 Step 3's key.

- [ ] **Step 1: Write the failing checks.**
  - **`test-skel-includes.sh`:** the policy has `.BrowserColorScheme == 2`, `has("BrowserThemeColor") | not`, and the extension list unchanged.
  - **If a key was found, in the smoke test:** `jq -e '<key path> == <value>' /etc/chromium/master_preferences` and `jq -e '.homepage == "https://fedoraproject.org/start"' /etc/chromium/master_preferences`, so Fedora's entries are kept.
- [ ] **Step 2: Run `bash tests/test-skel-includes.sh`.**
  Expected: FAIL.
- [ ] **Step 3: Implement.** Drop the key. Add the `jq` patch if applicable, written to a temp file and moved into place, and failing the build if `master_preferences` is missing.
- [ ] **Step 4: Run `just test`.**
  Expected: passes.
- [ ] **Step 5: Commit.** `feat(chromium): follow the GTK theme instead of a fixed frame colour`

### Task 7: Vesktop hook

**Files:**
- Create: `files/usr/share/atomic-hyprland/hooks/theme-set.d/41-vesktop`
- Create: `tests/test-vesktop-hook.sh` (wired into `just test`)
- Only in Task 1's fallback mode: `build/` fetches each pinned CSS, verified against a sha256 in the repo per `tests/test-build-pins.sh`'s rule, into `/usr/share/atomic-hyprland/vesktop/`.

**Interfaces:**
- Consumes: `vesktop` from `apps.toml` (Task 3); for monochrome and neon-night, `accent` from `colors.toml`; the variable names from Task 1 Step 5.
- Produces: `${HOME}/.var/app/dev.vencord.Vesktop/config/vesktop/themes/atomic-hyprland.css`.

- [ ] **Step 1: Write the failing test** (same stub pattern as Task 4). Cases:
  - **mapped URL** → the file is exactly `@import url("<url>");` plus a trailing newline.
  - **Midnight mapping** → the file also sets the accent variables to `colors.toml`'s `accent`.
  - **no Vesktop config folder** → no file; exit 0.
  - **no `apps.toml`, or an empty `vesktop` value** → no `atomic-hyprland.css` (removed if present); exit 0.
  - **bad URL** (`http://…`, an `@main/` path, a `"` or `;` in the URL) → treated as empty; exit 0.
  - **untouched files:** `settings/settings.json` and `settings/quickCss.css` are byte-identical after the hook.
- [ ] **Step 2: Run `bash tests/test-vesktop-hook.sh`.**
  Expected: FAIL (no hook).
- [ ] **Step 3: Implement `41-vesktop`.**
  - Validate the URL: `^https://` with no `"`, `;`, `)` or whitespace, and not `@main`, `@master` or `/refs/heads/`.
  - Write the file atomically.
  - No signal, because Vencord watches the folder (Task 1 Step 4). In fallback mode, copy `/usr/share/atomic-hyprland/vesktop/<theme>.css` instead.
- [ ] **Step 4: Run `bash tests/test-vesktop-hook.sh && just test`.**
  Expected: passes.
- [ ] **Step 5: Commit.** `feat(theme): Vesktop follows the desktop theme (hook 41-vesktop)`

### Task 8: Document the one-time steps

**Files:**
- Modify: `README.md`, the theming section around line 144

- [ ] **Step 1: Add a short "Apps that follow the theme" subsection.** It covers:
  - **Helix:** set `theme = "atomic-hyprland"` in an existing config (new users get it from skel); open editors pick it up live or with `:config-reload`, per Task 1.
  - **Chromium:** Settings → Appearance → Mode: GTK, once per existing profile.
  - **Vesktop:** Settings → Themes → enable "atomic-hyprland", once.
  - **Turning a hook off:** an empty, non-executable `~/.config/atomic-hyprland/hooks/theme-set.d/40-helix` or `41-vesktop`.
  - **Obsidian** is manual.
- [ ] **Step 2: Run `just test`.**
  Expected: passes.
- [ ] **Step 3: Commit.** `docs: apps that follow the theme, and their one-time steps`

## Findings (filled in by Task 1)

_Empty until Task 1 runs._
