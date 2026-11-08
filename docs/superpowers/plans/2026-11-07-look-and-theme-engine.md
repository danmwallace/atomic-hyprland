# Look and Theme Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the monochrome-green look on a runtime-switchable theme engine, move the Hyprland config from the Ansible role into this repo, and make CI prove every shipped theme renders and verifies.

**Architecture:** A bash engine (`hypr-theme`) renders `themed/*.tpl` from a theme's `colors.toml` into `~/.config/atomic-hyprland/current/theme/`; every app config in the image's skel carries one include line pointing there plus one `local` include the image never writes. Shipped Hyprland defaults live under `/usr/share/atomic-hyprland/hypr/` and are `require`d by a thin `hyprland.lua`. A user unit renders before the compositor through uwsm; waybar, mako, swaybg and hypridle are user units bound to `graphical-session.target`. The build stops running Ansible: packages come from `packages.txt`, files from `files/`.

**Tech Stack:** bash + sed/awk (engine), Hyprland 0.57 Lua config, waybar 0.15 (strict JSON), mako, wofi, hyprlock/hypridle, Ghostty/Alacritty, GTK via gsettings + Kvantum, SDDM QML theme, ImageMagick at build time only, existing bash test harness (`check`/`expect_out`), podman builds via `just`.

**Spec:** `docs/superpowers/specs/2026-11-07-look-and-theme-engine-design.md`

## Global Constraints

- Default theme name is `monochrome-green`; shipped themes: `monochrome-green`, `monochrome-blue`, `tokyo-night`, `nord`, `dracula`.
- Default accent `#39ff14`; `background #0a0a0a`, `background_alt #0c0c0c`, `surface #2a2a2a`, `foreground #c8c8c8`, `foreground_dim #8a8a8a`, `accent_dim #1f8f0b`, `warning #e0c060`, `critical #e05050`, `selection_background #2a2a2a`, `selection_foreground #e0e0e0`, `cursor_theme breeze_cursors`.
- Geometry everywhere: rounding 3, `gaps_in 4`, `gaps_out 8`, `border_size 2`, no blur, no shadows, no border/borderangle animation, no `special_scale_factor`.
- Bar: height 30, margins 8, right modules show a glyph only; numbers live in tooltips; `config.jsonc` must be strict JSON (`jq -e`).
- Placeholder forms: `{{ key }}` → `#rrggbb`, `{{ key_strip }}` → `rrggbb`, `{{ key_rgb }}` → `r,g,b`. An unresolved placeholder is a render error (exit 2), never silent text.
- `hypr-theme` skips every apply step when `HYPRLAND_INSTANCE_SIGNATURE` is unset or `--no-apply`/`HYPR_THEME_NO_APPLY=1` is given.
- Files the image writes in `$HOME`: only paths in `skel.manifest` (now `managed-files.txt`) and the removals in `skel.retired`. `local*` files are created empty once and never rewritten.
- Fonts: JetBrainsMono Nerd Font, pinned URL + sha256 as build ARGs like `TUIOS_SHA256`.
- New packages must be stated in the commit body (Dan's rule); third-party sources: only the Nerd Font tarball (already a pattern) — no new repos.
- Conventional Commits; the attribution footer from the session on every commit.
- Image builds are slow (~15 min). Smoke checks go RED cheaply against the previous published image (`podman run … ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/image-smoke.sh`); GREEN is proven at the two milestone builds (Task 4 and Task 10).

## Review Focus

1. `hypr-theme set` with a name containing `/`, `..`, spaces or uppercase: must be rejected (exit 1, message names the theme) and leave `current/` untouched. Test in Task 1.
2. A shipped theme missing one key another theme has: the render must fail naming theme and key, and the CI host test must catch it before any build. Test in Task 2.
3. `hypr-theme set` over SSH (no `HYPRLAND_INSTANCE_SIGNATURE`): renders, writes state, exits 0, runs no `hyprctl`/`systemctl`/`gsettings`. Test in Task 1.
4. An existing home with the role's old `waybar/config` and a user `waybar/local.jsonc`: after sync the old file is gone, `local.jsonc` is byte-identical, `config.jsonc` present. Test in Task 3.
5. A machine without a battery or NVIDIA card (hypr-test): `custom/gpu` prints valid JSON with the CPU temperature, the battery module is absent from the bar without a waybar error, hypridle's battery-only suspend does not fire. Tests in Task 5.

---

### Task 1: The theme engine (`hypr-theme`)

**Files:**
- Create: `files/usr/bin/hypr-theme` (bash, mode 0755)
- Create: `tests/test-hypr-theme.sh` (host-side; uses a fixture share dir)
- Create: `tests/fixtures/hypr-theme/share/themes/fixture/colors.toml`, `…/themes/fixture/backgrounds/00-a.png`, `…/themes/fixture/backgrounds/01-b.png` (1×1 PNGs), `…/themes/fixture/icons.theme` (`Papirus-Dark`), `…/share/themed/sample.conf.tpl`, `…/share/themed/hand.theme.tpl`, `…/share/themes/fixture/hand.theme` (theme-shipped file that must win over the template)
- Modify: `justfile:20-29` (add `bash tests/test-hypr-theme.sh` to `test`)

**Interfaces:**
- Produces: `hypr-theme list|current|set <name> [--keep-background] [--no-apply]|bg next|bg set <file>|refresh|render <tpl> <colors.toml>` (`render` writes to stdout; used by the build for SDDM in Task 8). Env: `HYPR_THEME_SHARE` (default `/usr/share/atomic-hyprland`), `HYPR_THEME_STATE` (default `$HOME/.config/atomic-hyprland`), `HYPR_THEME_NO_APPLY=1`, `HYPR_THEME_DEFAULT` (default `monochrome-green`). State layout: `$STATE/current/theme/`, `$STATE/current/background` (symlink), `$STATE/current/theme.name`, `$STATE/current/.checksum`. User overlay: `$STATE/themes/<name>/`, `$STATE/themed/*.tpl`. Exit codes: 0 ok, 1 usage/unknown theme/bad name, 2 render error. Apply hook dir: `$STATE/hooks/theme-set.d/`.
- Produces: the render rule used by every later template: for each `key = "#rrggbb"` line in `colors.toml` (also accepts unquoted and 3-digit-free; only 6-digit hex), substitute `{{ key }}`, `{{ key_strip }}`, `{{ key_rgb }}`; non-colour values (e.g. `cursor_theme = "breeze_cursors"`) substitute `{{ key }}` verbatim only. Whitespace inside braces is optional (`{{key}}` and `{{ key }}` both match).

- [ ] **Step 1: Write the failing host test**

`tests/test-hypr-theme.sh` (same `check`/`expect` style as `tests/test-ci-push.sh`), with `export HYPR_THEME_SHARE=tests/fixtures/hypr-theme/share HYPR_THEME_STATE="$(mktemp -d)" HYPR_THEME_NO_APPLY=1`; fixture `colors.toml`: `background = "#0a0a0a"`, `accent = "#39ff14"`, `cursor_theme = "breeze_cursors"`; `sample.conf.tpl` contains `bg={{ background }} strip={{ accent_strip }} rgb={{ accent_rgb }} cur={{cursor_theme}}`:

```bash
check bash -c 'hypr-theme list | grep -qx "fixture"'
check hypr-theme set fixture
check grep -qx 'bg=#0a0a0a strip=39ff14 rgb=57,255,20 cur=breeze_cursors' "$HYPR_THEME_STATE/current/theme/sample.conf"
check test "$(cat "$HYPR_THEME_STATE/current/theme.name")" = fixture
check test "$(hypr-theme current)" = fixture
check test "$(readlink "$HYPR_THEME_STATE/current/background")" = "$HYPR_THEME_SHARE/themes/fixture/backgrounds/00-a.png"
check grep -q 'hand-written' "$HYPR_THEME_STATE/current/theme/hand.theme"      # theme file beats template
check bash -c '! test -e "$HYPR_THEME_STATE/current/next-theme"'               # atomic swap left nothing behind
check bash -c 'hypr-theme bg next; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 01-b.png'
check bash -c 'hypr-theme bg next; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 00-a.png'   # wraps
check bash -c 'hypr-theme set fixture --keep-background; test "$(basename "$(readlink "$HYPR_THEME_STATE/current/background")")" = 00-a.png'
# overlay precedence: user copy of the theme wins over the shipped one
check bash -c 'mkdir -p "$HYPR_THEME_STATE/themes/fixture" && printf "background = \"#111111\"\naccent = \"#39ff14\"\ncursor_theme = \"x\"\n" > "$HYPR_THEME_STATE/themes/fixture/colors.toml" && hypr-theme set fixture && grep -q "bg=#111111" "$HYPR_THEME_STATE/current/theme/sample.conf"'
# user template wins over the shipped template
check bash -c 'mkdir -p "$HYPR_THEME_STATE/themed" && echo "mine={{ accent }}" > "$HYPR_THEME_STATE/themed/sample.conf.tpl" && hypr-theme refresh && grep -qx "mine=#39ff14" "$HYPR_THEME_STATE/current/theme/sample.conf"'
# refresh is idempotent: checksum unchanged, no rewrite
check bash -c 'before=$(stat -c %Y "$HYPR_THEME_STATE/current/theme/sample.conf"); sleep 1; hypr-theme refresh; test "$(stat -c %Y "$HYPR_THEME_STATE/current/theme/sample.conf")" = "$before"'
# unresolved placeholder is an error naming template and key
check bash -c 'echo "x={{ nope }}" > "$HYPR_THEME_STATE/themed/bad.tpl"; hypr-theme refresh 2>&1 | grep -q "bad.tpl: unresolved placeholder {{ nope }}"; test ${PIPESTATUS[0]} = 2; rm "$HYPR_THEME_STATE/themed/bad.tpl"'
# bad names (Review Focus 1)
for bad in "../x" "a/b" "Fixture" "has space" ""; do
  check bash -c "! hypr-theme set '$bad' >/dev/null 2>&1"
done
check test "$(hypr-theme current)" = fixture
check bash -c 'hypr-theme set nonexistent 2>&1 | grep -q "unknown theme: nonexistent"'
check bash -c '! hypr-theme set nonexistent >/dev/null 2>&1'
check test "$(hypr-theme render "$HYPR_THEME_SHARE/themed/sample.conf.tpl" "$HYPR_THEME_SHARE/themes/fixture/colors.toml")" = 'bg=#0a0a0a strip=39ff14 rgb=57,255,20 cur=breeze_cursors'
# no session (Review Focus 3): unset the signature, drop NO_APPLY, stub the apply commands to a logging PATH
check bash -c 'unset HYPR_THEME_NO_APPLY HYPRLAND_INSTANCE_SIGNATURE; bin=$(mktemp -d); for c in hyprctl systemctl gsettings flatpak kvantummanager pkill swaybg; do printf "#!/bin/sh\necho called-%s >> %s\n" "$c" "$bin/log" > "$bin/$c"; chmod +x "$bin/$c"; done; PATH="$bin:$PATH" hypr-theme set fixture && ! test -e "$bin/log"'
# with a session the apply commands run
check bash -c 'unset HYPR_THEME_NO_APPLY; export HYPRLAND_INSTANCE_SIGNATURE=test; bin=$(mktemp -d); for c in hyprctl systemctl gsettings flatpak kvantummanager pkill swaybg; do printf "#!/bin/sh\necho called-%s >> %s\n" "$c" "$bin/log" > "$bin/$c"; chmod +x "$bin/$c"; done; PATH="$bin:$PATH" hypr-theme set fixture && grep -q called-hyprctl "$bin/log" && grep -q called-systemctl "$bin/log" && grep -q called-gsettings "$bin/log"'
# hook dir runs on apply (signature set, stub PATH, no --no-apply) and gets the theme name
check bash -c 'unset HYPR_THEME_NO_APPLY; export HYPRLAND_INSTANCE_SIGNATURE=test; bin=$(mktemp -d); for c in hyprctl systemctl gsettings flatpak kvantummanager pkill swaybg; do printf "#!/bin/sh\n" > "$bin/$c"; chmod +x "$bin/$c"; done; mkdir -p "$HYPR_THEME_STATE/hooks/theme-set.d"; printf "#!/bin/sh\necho \$1 > %s/hook.out\n" "$HYPR_THEME_STATE" > "$HYPR_THEME_STATE/hooks/theme-set.d/10-test"; chmod +x "$HYPR_THEME_STATE/hooks/theme-set.d/10-test"; PATH="$bin:$PATH" hypr-theme set fixture && test "$(cat "$HYPR_THEME_STATE/hook.out")" = fixture'
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PATH="$PWD/files/usr/bin:$PATH" bash tests/test-hypr-theme.sh`
Expected: every line `FAIL` (`hypr-theme: command not found`).

- [ ] **Step 3: Implement `files/usr/bin/hypr-theme`**

bash, `set -euo pipefail`. Functions: `die msg [code]`, `valid_name` (`^[a-z0-9][a-z0-9-]*$`), `theme_dir name` (user overlay dir if it has `colors.toml`, else shipped; both searched by `list`), `render tpl colors out` (build a sed script from `colors.toml`: for 6-hex values emit the three substitutions, for other quoted values the plain one; run `sed -f`; afterwards `grep -oE '\{\{ *[a-z0-9_]+ *\}\}'` on the output → `die "<tpl basename>: unresolved placeholder {{ key }}" 2`), `build_next name` (`rm -rf next-theme; cp -a shipped; cp -a overlay over it if present; for tpl in user themed/*.tpl then shipped themed/*.tpl: out="next-theme/${tpl%.tpl}"; [ -e out ] && continue; render`), `swap` (`rm -rf current/theme; mv next-theme current/theme; echo name > theme.name`), `checksum` (sha256 over the sorted content of the inputs: colors.toml, template list+contents, overlay; stored in `current/.checksum`; `refresh` returns early when equal), `set_background` (first sorted file in theme `backgrounds/` plus `~/Pictures/Wallpapers`; `ln -nsf`), `bg_next` (sorted list, index of current, wrap), `apply` (skipped when `--no-apply`, `HYPR_THEME_NO_APPLY=1`, or `HYPRLAND_INSTANCE_SIGNATURE` unset; otherwise each command guarded with `command -v`: `hyprctl reload`; `systemctl --user try-restart waybar.service mako.service`; `pkill -SIGUSR2 -x ghostty || true`; `touch ~/.config/alacritty/alacritty.toml`; `gsettings set org.gnome.desktop.interface color-scheme prefer-dark`, `gtk-theme Adwaita-dark`, `icon-theme "$(cat icons.theme)"`, `cursor-theme "<cursor_theme from colors.toml>"`; `flatpak override --user --env=GTK_THEME=Adwaita:dark --filesystem=xdg-config/gtk-3.0:ro --filesystem=xdg-config/gtk-4.0:ro`; `kvantummanager --set atomic-hyprland` if a Kvantum theme dir exists; restart swaybg via `systemctl --user try-restart swaybg.service`; then run executables in `hooks/theme-set.d/` with the theme name as `$1`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `PATH="$PWD/files/usr/bin:$PATH" bash tests/test-hypr-theme.sh`
Expected: all `ok`, exit 0. Also `shellcheck files/usr/bin/hypr-theme` clean (shellcheck is in the Fedora repos: `sudo dnf install ShellCheck`; if absent, note it and skip).

- [ ] **Step 5: Commit**

```bash
git add files/usr/bin/hypr-theme tests/test-hypr-theme.sh tests/fixtures/hypr-theme justfile
git commit -m "feat(theme): add hypr-theme, the runtime theme renderer"
```

---

### Task 2: Palettes, wallpaper template and the theme consistency test

**Files:**
- Create: `files/usr/share/atomic-hyprland/themes/{monochrome-green,monochrome-blue,tokyo-night,nord,dracula}/colors.toml` and `…/icons.theme` (`Papirus-Dark` for all five)
- Create: `files/usr/share/atomic-hyprland/themed/wallpaper.svg.tpl` (3840×2160 SVG: `<radialGradient cx="50%" cy="40%" r="75%">` from `{{ background }}` lightened to `#171717`-equivalent at the centre to `{{ background }}` at the edge; the builder expresses "lightened ~6 %" as a second colour key `background_glow` in every `colors.toml` rather than computing it in SVG)
- Create: `build/render-wallpapers.sh` (build time: for each shipped theme, render `wallpaper.svg.tpl` with the Task 1 engine, `rsvg-convert`/`magick` to `themes/<name>/backgrounds/00-plain.png`)
- Create: `tests/test-themes.sh` (host)
- Modify: `justfile` `test` recipe (add `bash tests/test-themes.sh`)

**Interfaces:**
- Consumes: Task 1's render rule and `HYPR_THEME_SHARE`.
- Produces: the required key set, identical in all five files: `background background_glow background_alt surface foreground foreground_dim accent accent_dim warning critical selection_background selection_foreground cursor_theme color0 … color15`. Every later template may use only these keys.

- [ ] **Step 1: Write the failing host test**

```bash
# tests/test-themes.sh
required="background background_glow background_alt surface foreground foreground_dim accent accent_dim warning critical selection_background selection_foreground cursor_theme $(seq -f 'color%g' 0 15 | tr '\n' ' ')"
for t in monochrome-green monochrome-blue tokyo-night nord dracula; do
  f="files/usr/share/atomic-hyprland/themes/$t/colors.toml"
  check test -f "$f"
  check test -s "files/usr/share/atomic-hyprland/themes/$t/icons.theme"
  for k in $required; do check grep -qE "^$k = \"" "$f"; done
  # every colour is 6-digit hex; cursor_theme is a plain word
  check bash -c "! grep -E '^(color[0-9]+|background.*|surface|foreground.*|accent.*|warning|critical|selection_.*) = ' '$f' | grep -vqE '= \"#[0-9a-f]{6}\"$'"
  # no extra keys beyond the set (so templates cannot depend on a key one theme lacks)
  check bash -c "diff <(grep -oE '^[a-z0-9_]+' '$f' | sort) <(tr ' ' '\n' <<< '$required' | grep . | sort)"
done
check test "$(grep -E '^accent = ' files/usr/share/atomic-hyprland/themes/monochrome-green/colors.toml)" = 'accent = "#39ff14"'
check test "$(grep -E '^accent = ' files/usr/share/atomic-hyprland/themes/monochrome-blue/colors.toml)" = 'accent = "#3d9bff"'
# every shipped template renders against every theme with no unresolved placeholder (Review Focus 2)
for t in monochrome-green monochrome-blue tokyo-night nord dracula; do
  check env HYPR_THEME_SHARE=files/usr/share/atomic-hyprland HYPR_THEME_STATE="$(mktemp -d)" HYPR_THEME_NO_APPLY=1 files/usr/bin/hypr-theme set "$t"
done
check test -f files/usr/share/atomic-hyprland/themed/wallpaper.svg.tpl
check grep -q '{{ background_glow }}' files/usr/share/atomic-hyprland/themed/wallpaper.svg.tpl
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tests/test-themes.sh`
Expected: FAIL on the missing files.

- [ ] **Step 3: Write the five `colors.toml` files, `icons.theme`, `wallpaper.svg.tpl`, `build/render-wallpapers.sh`**

monochrome-green values are pinned in Global Constraints; `background_glow = "#171717"`; color0–15: `0 #0a0a0a`, `8 #2a2a2a`, `7 #c8c8c8`, `15 #e0e0e0`, `2/10 #39ff14`, `1/9 #e05050`, `3/11 #e0c060`, `4/12 #6f8a99`, `5/13 #8a6f99`, `6/14 #6f9999` (tinted greys). monochrome-blue: same greys, `accent #3d9bff`, `accent_dim #1f5a99`, `background_glow #15171c`, `2/10 #3d9bff`. tokyo-night, nord, dracula: the published palettes mapped onto the keys (`accent` = the palette's primary blue/frost/purple). `render-wallpapers.sh`: `set -euo pipefail`; needs `rsvg-convert` (package `librsvg2-tools`) installed and removed by Task 4's build step; for each theme: `HYPR_THEME_NO_APPLY=1 HYPR_THEME_STATE=$(mktemp -d) hypr-theme set $t`, then `rsvg-convert -w 3840 -h 2160 current/theme/wallpaper.svg -o themes/$t/backgrounds/00-plain.png`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash tests/test-themes.sh`
Expected: all `ok`.

- [ ] **Step 5: Commit**

```bash
git add files/usr/share/atomic-hyprland/themes files/usr/share/atomic-hyprland/themed/wallpaper.svg.tpl build/render-wallpapers.sh tests/test-themes.sh justfile
git commit -m "feat(theme): ship five palettes and the generated plain wallpaper"
```

---

### Task 3: `sync-dotfiles` ownership rules and the pre-compositor render unit

**Files:**
- Modify: `files/usr/libexec/atomic-hyprland/sync-dotfiles`
- Create: `files/usr/lib/systemd/user/atomic-hyprland-theme.service`
- Create: `files/usr/libexec/atomic-hyprland/ensure-theme` (bash, 0755)
- Create: `files/usr/share/atomic-hyprland/skel.retired`, `files/usr/share/atomic-hyprland/skel.local` (list of `local` files to create once)
- Modify: `tests/test-sync-dotfiles.sh`
- Modify: `build/40-finalize.sh:14-24` (the `managed-files.txt` generation and the new `--global enable`)

**Interfaces:**
- Consumes: Task 1 `hypr-theme set <name> --keep-background --no-apply`, `HYPR_THEME_DEFAULT`.
- Produces: `sync-dotfiles` semantics: (1) install every manifest path; (2) create each path in `skel.local` from `skel/` if absent, never rewrite; (3) remove each path in `skel.retired` (files; directories with `rm -rf` only when the entry ends in `/`); (4) write the stamp. `atomic-hyprland-theme.service`: `After=atomic-hyprland-dotfiles.service`, `Before=wayland-session-pre@Hyprland.target`, `ConditionPathExists=/usr/share/atomic-hyprland/stamp`, `ExecStart=/usr/libexec/atomic-hyprland/ensure-theme` (new small script: renders when `current/theme/` is missing or `current/.stamp` ≠ image stamp), `WantedBy=wayland-session-pre@Hyprland.target`.

- [ ] **Step 1: Extend the failing test**

Append to `tests/test-sync-dotfiles.sh` (it already builds a throwaway share; add fixture entries to it before running):

```bash
# 7. local files are created once and never rewritten
printf '.config/waybar/local.jsonc\n.config/ghostty/local\n' > "${share}/skel.local"
mkdir -p "${share}/skel/.config/waybar" "${share}/skel/.config/ghostty"; echo '{}' > "${share}/skel/.config/waybar/local.jsonc"; : > "${share}/skel/.config/ghostty/local"
export HOME="$(mktemp -d)"; "${sync}"
expect "local.jsonc created" 'test "$(cat "$HOME/.config/waybar/local.jsonc")" = "{}"'
echo '{"custom/x":{}}' > "$HOME/.config/waybar/local.jsonc"; echo newer2 > "${share}/stamp"; "${sync}"
expect "local.jsonc never rewritten" 'grep -q custom/x "$HOME/.config/waybar/local.jsonc"'
expect "local files not in managed list" '! grep -q "local.jsonc" "$share/managed-files.txt"'
# 8. retired paths are removed; user files beside them survive (Review Focus 4)
printf '.config/waybar/config\n.config/hypr/conf/\n.config/nwg-drawer/\n' > "${share}/skel.retired"
export HOME="$(mktemp -d)"; mkdir -p "$HOME/.config/waybar" "$HOME/.config/hypr/conf" "$HOME/.config/nwg-drawer"
echo old > "$HOME/.config/waybar/config"; echo old > "$HOME/.config/hypr/conf/look.lua"; echo old > "$HOME/.config/nwg-drawer/drawer.css"
echo mine > "$HOME/.config/waybar/local.jsonc"
"${sync}"
expect "old waybar/config removed" '! test -e "$HOME/.config/waybar/config"'
expect "old conf dir removed" '! test -e "$HOME/.config/hypr/conf"'
expect "old nwg-drawer removed" '! test -e "$HOME/.config/nwg-drawer"'
expect "user local.jsonc untouched by retirement" 'test "$(cat "$HOME/.config/waybar/local.jsonc")" = mine'
# 9. theme unit ordered before the compositor and enabled for every user
expect "theme unit enabled globally" 'test -L /etc/systemd/user/wayland-session-pre@Hyprland.target.wants/atomic-hyprland-theme.service'
expect "theme unit runs after dotfiles" 'grep -q "^After=atomic-hyprland-dotfiles.service" /usr/lib/systemd/user/atomic-hyprland-theme.service'
expect "theme unit runs before the session" 'grep -q "^Before=wayland-session-pre@Hyprland.target" /usr/lib/systemd/user/atomic-hyprland-theme.service'
# 10. ensure-theme renders on first login and is a no-op afterwards
export HOME="$(mktemp -d)" HYPR_THEME_SHARE="${share}" HYPR_THEME_NO_APPLY=1
mkdir -p "${share}/themes/t/backgrounds" "${share}/themed"; printf 'background = "#000000"\n' > "${share}/themes/t/colors.toml"; : > "${share}/themes/t/backgrounds/a.png"; echo 'x={{ background }}' > "${share}/themed/x.tpl"
HYPR_THEME_DEFAULT=t /usr/libexec/atomic-hyprland/ensure-theme
expect "ensure-theme rendered the default theme" 'test -f "$HOME/.config/atomic-hyprland/current/theme/x"'
expect "ensure-theme recorded the stamp" 'cmp -s "$share/stamp" "$HOME/.config/atomic-hyprland/current/.stamp"'
out="$(HYPR_THEME_DEFAULT=t /usr/libexec/atomic-hyprland/ensure-theme)"
expect "ensure-theme no-op on same stamp" '[[ "$out" == *"up to date"* ]]'
```

Also update the two existing lines that assert the old waybar path: `expect "waybar config synced" 'test -f "$HOME/.config/waybar/config.jsonc"'` and replace the `sleep.sh stays executable` check with `hypr-power` later (Task 6) — for now assert `test -x "$HOME/.config/waybar/scripts/gpu"` only after Task 5; in this task change it to assert on a fixture executable you add to the throwaway share.

- [ ] **Step 2: Run on the host against the fixture share to verify it fails**

The test runs inside the image, but `sync-dotfiles` only needs `ATOMIC_HYPRLAND_SHARE`; run: `sed 's|/usr/libexec/atomic-hyprland/sync-dotfiles|files/usr/libexec/atomic-hyprland/sync-dotfiles|; s|/usr/libexec/atomic-hyprland/ensure-theme|files/usr/libexec/atomic-hyprland/ensure-theme|; s|cp -a /usr/share/atomic-hyprland/.|cp -a tests/fixtures/sync/share/.|' tests/test-sync-dotfiles.sh > /tmp/claude-1000/-home-dwallace-Code-atomic-hyprland/4f0770dd-911a-4c50-92a4-24dd2795e1bd/scratchpad/sync-host.sh && PATH="$PWD/files/usr/bin:$PATH" bash /tmp/claude-1000/-home-dwallace-Code-atomic-hyprland/4f0770dd-911a-4c50-92a4-24dd2795e1bd/scratchpad/sync-host.sh` (create `tests/fixtures/sync/share/` with a `stamp`, a minimal `skel/.config/hypr/{hyprland.lua,local.lua}` and `managed-files.txt`).
Expected: items 7–10 FAIL; the unit checks FAIL (files absent on host — acceptable, they are proven at the Task 4 build).

- [ ] **Step 3: Implement**

`sync-dotfiles`: read `skel.local` and `skel.retired` (both optional) with the same comment/blank skipping as the manifest; retirement runs before installing; keep the existing `local.lua` special case by moving `.config/hypr/local.lua` into `skel.local`. `ensure-theme`: `set -euo pipefail`; `state="${HYPR_THEME_STATE:-$HOME/.config/atomic-hyprland}"`; if `current/theme` exists and `current/.stamp` equals the image stamp → print `atomic-hyprland theme: up to date` and exit 0; else `name=$(cat current/theme.name 2>/dev/null || echo "${HYPR_THEME_DEFAULT:-monochrome-green}")`; `hypr-theme set "$name" --keep-background --no-apply`; copy the stamp to `current/.stamp`. The unit file as in Interfaces. `40-finalize.sh`: exclude `skel.local` entries from `managed-files.txt` (`grep -vxFf /usr/share/atomic-hyprland/skel.local`), `systemctl --global enable atomic-hyprland-theme.service`, and write `skel.retired` content from `files/` (it is a static file in `files/`, nothing to generate).

- [ ] **Step 4: Run the host variant again**

Expected: items 1–8 and 10 `ok`; only the two `/usr/lib/systemd` unit-file checks FAIL on the host (deferred to Task 4's build).

- [ ] **Step 5: Commit**

```bash
git add files/usr/libexec/atomic-hyprland files/usr/lib/systemd/user/atomic-hyprland-theme.service files/usr/share/atomic-hyprland/skel.retired files/usr/share/atomic-hyprland/skel.local tests/test-sync-dotfiles.sh tests/fixtures/sync build/40-finalize.sh
git commit -m "feat(dotfiles): local files, retired paths, render the theme before the session"
```

---

### Task 4: Hyprland config in the repo, Ansible out of the build (milestone build 1)

**Files:**
- Create: `files/usr/share/atomic-hyprland/hypr/{env,input,binds,rules,look,monitors,autostart}.lua` (ported from the role's `conf/*.lua.j2` with the spec's pinned look; `autostart.lua` keeps only portal/polkit/keyring/cliphist `exec_cmd`s — waybar, mako, swaybg, hypridle move to units in Task 5)
- Create: `files/usr/share/atomic-hyprland/themed/hyprland.lua.tpl` (sets global `palette = { background = "{{ background_strip }}", … }` for every key; strip form because Hyprland colours are `rgb(rrggbb)`)
- Create: `files/etc/skel/.config/hypr/hyprland.lua` (thin: `package.path = "/usr/share/atomic-hyprland/hypr/?.lua;" .. package.path`; `local ok = pcall(dofile, os.getenv("HOME") .. "/.config/atomic-hyprland/current/theme/hyprland.lua"); if not ok or not palette then palette = { …default monochrome-green strip values… } end`; `require` each default in the role's order; `pcall(require, "local")`), `files/etc/skel/.config/hypr/local.lua` (comment-only template as today)
- Delete: `build/20-hyprland-role.sh`, `build/playbook.yml`, `build/requirements.yml`
- Create: `build/20-desktop.sh` (installs `librsvg2-tools` for the build only, runs `build/render-wallpapers.sh`, installs the Nerd Font: see Task 7 for the pin — in this task install nothing font-related yet)
- Modify: `build/packages.txt` (add the role's package list minus the removals: `hyprland hyprland-guiutils hyprpicker hypridle hyprlock hyprpolkitagent xdg-desktop-portal-hyprland xdg-desktop-portal-gtk sddm sddm-x11 waybar alacritty wofi swaybg cliphist wl-clipboard grim slurp pamixer pavucontrol brightnessctl bluez bluez-tools tuned tuned-ppd network-manager-applet NetworkManager-wifi nm-connection-editor-desktop gnome-keyring qt5-qtwayland qt6-qtwayland cups-pk-helper nautilus simple-scan alsa-sof-firmware alsa-utils gvfs gvfs-mtp uwsm hyprland-uwsm`; not `hyprpaper waypaper nwg-drawer nwg-dock-hyprland qt6ct blueman light`)
- Modify: `build/10-packages.sh` (drop the `ansible-core python3-libdnf5` install), `build/90-cleanup.sh` (drop the ansible removal; add `dnf -y remove librsvg2-tools`), `Containerfile` (drop `ARG THEME`, replace the role `RUN` with `RUN /tmp/build/20-desktop.sh`; `COPY files/ /` must now come **before** `20-desktop.sh` because the wallpaper render needs `hypr-theme` and the themes — move the `COPY files/` line above and keep `cosign.pub`/policy where they are), `justfile` (`build` loses the `theme` parameter and `--build-arg THEME`), `tests/test-justfile.sh` (assert `just --show build` has no `THEME`), `tests/image-smoke.sh` (see Step 1)
- Modify: `README.md` "Local loop" (the `just build nord` form disappears)

**Interfaces:**
- Consumes: Task 1 engine, Task 2 themes, Task 3 sync rules.
- Produces: `/usr/share/atomic-hyprland/hypr/*.lua` read `palette.<key>` (strip hex) and `palette.cursor_theme`; `look.lua` pins `gaps_in 4, gaps_out 8, border_size 2, rounding 3, blur.enabled false, shadow.enabled false`, `col.active_border = "rgb(" .. palette.accent .. ")"`, `col.inactive_border = "rgb(" .. palette.surface .. ")"`; `binds.lua` exposes `terminal = "ghostty"`, `menu = "wofi --show drun"`, `lock = "hyprlock"`, `power = "hypr-power"`, and the laptop keys (`XF86MonBrightnessUp/Down → brightnessctl s 5%+/5%-`, `XF86AudioRaiseVolume/LowerVolume/Mute → pamixer`, `XF86AudioMicMute → pamixer --default-source -t`, `bindl switch:on:Lid Switch → hyprlock` via `hl.bind` with the `l` flag).

- [ ] **Step 1: Rewrite the Hyprland section of `tests/image-smoke.sh` (RED against the published image)**

Replace the `/etc/skel/.config/hypr/conf/*` assertions and the wallpaper lines with:

```bash
check bash -c '! rpm -q ansible-core python3-libdnf5 hyprpaper nwg-drawer nwg-dock-hyprland qt6ct waypaper'
check rpm -q uwsm hyprland-uwsm file
check bash -c '! rpm -q librsvg2-tools'   # build-time only
for f in env input binds rules look monitors autostart; do check test -f /usr/share/atomic-hyprland/hypr/$f.lua; done
check bash -c '! grep -rq special_scale_factor /usr/share/atomic-hyprland /etc/skel'
check grep -q 'rounding = 3' /usr/share/atomic-hyprland/hypr/look.lua
check grep -q 'gaps_out = 8' /usr/share/atomic-hyprland/hypr/look.lua
check bash -c '! test -e /etc/skel/.config/hypr/conf'
check grep -q 'package.path = "/usr/share/atomic-hyprland/hypr/?.lua;"' /etc/skel/.config/hypr/hyprland.lua
check grep -q 'pcall(require, "local")' /etc/skel/.config/hypr/hyprland.lua
for t in monochrome-green monochrome-blue tokyo-night nord dracula; do
  check test -f /usr/share/atomic-hyprland/themes/$t/backgrounds/00-plain.png
  check bash -c "file /usr/share/atomic-hyprland/themes/$t/backgrounds/00-plain.png | grep -q '3840 x 2160'"
done
check test -f /usr/lib/systemd/user/atomic-hyprland-theme.service
check test -L /etc/systemd/user/wayland-session-pre@Hyprland.target.wants/atomic-hyprland-theme.service
```

and change `verify_hypr` to render a theme first: it takes the theme name as `$3` (default `monochrome-green`), runs `HYPR_THEME_SHARE=/usr/share/atomic-hyprland HYPR_THEME_STATE=$HOME/.config/atomic-hyprland HYPR_THEME_NO_APPLY=1 hypr-theme set "$3"` as part of the HOME setup (before `chown`), and the probe/`binds`/`look` append targets become `/tmp/hv/extra-binds.lua`/`extra-look.lua` that the test `require`s by appending `require("extra_binds")` lines to the thin `hyprland.lua` (copy them into `$HOME/.config/hypr/`). Then loop:

```bash
for t in monochrome-green monochrome-blue tokyo-night nord dracula; do
  out="$(verify_hypr '' '' "$t")"
  expect_out "hyprland verify-config exits 0 for $t" present '^VERIFY_EXIT=0$'
  expect_out "hyprland reports config ok for $t" present 'config ok'
  expect_out "no unresolved placeholder for $t" absent '\{\{'
done
# the fallback palette works when the theme file is missing
out="$(HV_NO_THEME=1 verify_hypr)"      # verify_hypr skips the render when HV_NO_THEME=1
expect_out "hyprland verifies with the built-in fallback palette" present '^VERIFY_EXIT=0$'
```

Run the smoke against the previous image: `podman run --rm -e PUBKEY_SHA256="$(sha256sum cosign.pub | cut -d' ' -f1)" -v ./tests:/tests:ro,Z ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/image-smoke.sh 2>&1 | grep -c FAIL`
Expected: a non-zero FAIL count that includes the new lines (the old image has the role's layout).

- [ ] **Step 2: Port the Lua config, write the template and the thin entrypoint, change the build**

Port each `conf/*.lua.j2` to a plain `.lua` under `files/usr/share/atomic-hyprland/hypr/`, replacing `{{ hyprland_wallpaper }}` and other Jinja with nothing (wallpaper moves to the swaybg unit in Task 5) and applying the pinned look values; `binds.lua` replaces `alacritty` with `ghostty`, `wlogout -p layer-shell` with `hypr-power`, `thunar` with `nautilus`, `firefox` with `chromium-browser`. `hyprland.lua.tpl` emits every key in the Task 2 set as `key = "{{ key_strip }}"` (and `cursor_theme = "{{ cursor_theme }}"`). Build changes as listed under Files. `20-desktop.sh`: `dnf -y install --setopt=install_weak_deps=False librsvg2-tools file` then `PATH=/usr/bin /tmp/build/render-wallpapers.sh` (it uses `/usr/bin/hypr-theme` from the already-copied `files/`); `file` is needed by the smoke `3840 x 2160` check and stays.

- [ ] **Step 3: Build and run the full suite (milestone build 1)**

Run: `just build && just test 2>&1 | tee /tmp/claude-1000/-home-dwallace-Code-atomic-hyprland/4f0770dd-911a-4c50-92a4-24dd2795e1bd/scratchpad/test-m1.log | grep -E "^FAIL|VERIFY_EXIT|passed|failed" | head -40`
Expected: no `FAIL` lines except those owned by Tasks 5–8 (waybar/mako/wofi/hyprlock/GTK/SDDM checks do not exist yet, so there should be none); five `config ok`; the sync-dotfiles test fully green including the unit checks. If `Hyprland --verify-config` rejects `package.path` assignment or `dofile`, fall back to the spec's "theme file `return`s the table and defaults `require` it" variant and ledger the ruling.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(image)!: Hyprland config lives in the image; Ansible leaves the build

New build-time-only package: librsvg2-tools (removed in cleanup). New runtime
package: file. Removed: hyprpaper, waypaper, nwg-drawer, nwg-dock-hyprland,
qt6ct, blueman, light. BREAKING CHANGE: THEME build arg removed; the image
ships every theme and defaults to monochrome-green."
```

---

### Task 5: Waybar, mako, swaybg, hypridle as session units; the quiet bar

**Files:**
- Create: `files/etc/skel/.config/waybar/config.jsonc` (strict JSON), `files/etc/skel/.config/waybar/style.css`, `files/etc/skel/.config/waybar/local.jsonc` (`{}`), `files/etc/skel/.config/waybar/local.css` (empty)
- Create: `files/usr/share/atomic-hyprland/themed/waybar.css.tpl` (`@define-color background {{ background_alt }};` … for `surface foreground foreground_dim accent accent_dim warning critical`)
- Create: `files/usr/libexec/atomic-hyprland/waybar/gpu` (bash; prints `{"text":"󰢮","tooltip":"gpu 71 °C","class":"normal|critical","percentage":71}`; uses `nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits` when `/proc/driver/nvidia/version` exists, else the CPU package from `/sys/class/thermal` or `/sys/class/hwmon` (`coretemp`/`k10temp`); class `critical` at ≥ 80)
- Create: `files/usr/libexec/atomic-hyprland/waybar/notifications` (mako do-not-disturb state via `makoctl mode`; classes `dnd`/`normal`; glyphs `󰂛`/`󰂚`)
- Create: `files/usr/lib/systemd/user/{waybar,mako,swaybg,hypridle}.service` (each `[Unit] PartOf=graphical-session.target After=graphical-session.target Requisite=graphical-session.target`, `[Install] WantedBy=graphical-session.target`; swaybg `ExecStart=/usr/bin/swaybg -m fill -i %h/.config/atomic-hyprland/current/background`, `Restart=on-failure`)
- Create: `files/etc/skel/.config/mako/local` (empty); `files/usr/share/atomic-hyprland/mako/core.ini` (geometry: `border-radius=3`, `border-size=1`, `width=360`, `anchor=top-right`, `margin=46,12,0,0` (46 = 8 margin + 30 bar + 8 gap), `default-timeout=6000`, `font=JetBrainsMono Nerd Font 11`, `[urgency=critical] default-timeout=0`); `files/usr/share/atomic-hyprland/themed/mako.ini.tpl` (`include=/usr/share/atomic-hyprland/mako/core.ini` first, colours, `include=~/.config/mako/local` last, and `[urgency=critical] border-color={{ critical }}`)
- Create: `files/etc/skel/.config/hypr/hypridle.conf`, `files/etc/skel/.config/hypr/hypridle.local.conf` (empty)
- Create: `files/usr/libexec/atomic-hyprland/battery-warn` + `files/usr/lib/systemd/user/atomic-hyprland-battery.{service,timer}` (every 2 min; `ConditionPathExistsGlob=/sys/class/power_supply/BAT*`; notifies once below 15 % via `notify-send -u critical`, resets when charging)
- Create: `tests/test-waybar.sh` (host)
- Modify: `build/40-finalize.sh` (`systemctl --global enable waybar.service mako.service swaybg.service hypridle.service atomic-hyprland-battery.timer`), `files/usr/share/atomic-hyprland/skel.local` (add `.config/waybar/local.jsonc .config/waybar/local.css .config/mako/local .config/hypr/hypridle.local.conf`), `files/usr/share/atomic-hyprland/skel.retired` (`.config/waybar/config .config/waybar/mediaplayer.py`), `files/usr/share/atomic-hyprland/hypr/autostart.lua` (no waybar/swaybg/hypridle exec), `build/packages.txt` (`mako libnotify` — `notify-send` — ), `tests/image-smoke.sh`, `justfile` test recipe (add `bash tests/test-waybar.sh`)

**Interfaces:**
- Consumes: Task 2 keys; Task 1 `hypr-theme set` restarts `waybar.service mako.service swaybg.service`; Task 3 `skel.local`/`skel.retired`.
- Produces: `config.jsonc` module order left `hyprland/workspaces, hyprland/window`; center `clock`; right `group/tray-drawer, bluetooth, network, pulseaudio, cpu, memory, custom/gpu, battery, idle_inhibitor, custom/notifications, custom/power`; `"include": ["~/.config/waybar/local.jsonc"]`; `style.css` begins `@import "../atomic-hyprland/current/theme/waybar.css";` and ends `@import "local.css";`. `custom/power` → `hypr-power` (Task 6). mako symlink target `~/.config/atomic-hyprland/current/theme/mako.ini` (the symlink `~/.config/mako/config` is in the skel and the manifest).

- [ ] **Step 1: Write the failing host test**

```bash
# tests/test-waybar.sh
cfg=files/etc/skel/.config/waybar/config.jsonc
check jq -e . "$cfg"
check bash -c 'jq -e ".\"modules-right\" == [\"group/tray-drawer\",\"bluetooth\",\"network\",\"pulseaudio\",\"cpu\",\"memory\",\"custom/gpu\",\"battery\",\"idle_inhibitor\",\"custom/notifications\",\"custom/power\"]" '"$cfg"
check bash -c 'jq -e ".height == 30 and .\"margin-top\" == 8 and .\"margin-left\" == 8 and .\"margin-right\" == 8 and .\"reload_style_on_change\" == true" '"$cfg"
check bash -c 'jq -e ".include == [\"~/.config/waybar/local.jsonc\"]" '"$cfg"
# glyph-only default formats: no "{" value placeholders other than {icon} in the right-hand modules' format
check bash -c 'for m in cpu memory battery network pulseaudio bluetooth; do jq -er ".\"$m\".format" '"$cfg"' | grep -vqE "\{(capacity|usage|percentage|volume|essid|ipaddr|signalStrength)"; done'
check bash -c 'jq -er ".\"custom/gpu\".exec" '"$cfg"' | grep -q "/usr/libexec/atomic-hyprland/waybar/gpu"'
check bash -c 'jq -er ".battery.states.critical == 15 and .battery.states.warning == 30" '"$cfg"
check bash -c 'jq -er ".\"custom/power\".\"on-click\"" '"$cfg"' | grep -qx hypr-power'
check bash -c 'head -1 files/etc/skel/.config/waybar/style.css | grep -qx "@import \"../atomic-hyprland/current/theme/waybar.css\";"'
check bash -c 'tail -1 files/etc/skel/.config/waybar/style.css | grep -qx "@import \"local.css\";"'
check grep -q '#battery.charging' files/etc/skel/.config/waybar/style.css
check grep -q '#custom-gpu.critical' files/etc/skel/.config/waybar/style.css
check jq -e . files/etc/skel/.config/waybar/local.jsonc
# scripts emit valid JSON with and without hardware (Review Focus 5)
bin=$(mktemp -d); printf '#!/bin/sh\necho 71\n' > "$bin/nvidia-smi"; chmod +x "$bin/nvidia-smi"
fakeproc=$(mktemp -d); mkdir -p "$fakeproc/driver/nvidia"; echo x > "$fakeproc/driver/nvidia/version"
check bash -c 'PATH="'"$bin"':$PATH" GPU_PROC_ROOT="'"$fakeproc"'" files/usr/libexec/atomic-hyprland/waybar/gpu | jq -e ".percentage == 71 and .class == \"normal\" and .text == \"󰢮\""'
printf '#!/bin/sh\necho 84\n' > "$bin/nvidia-smi"
check bash -c 'PATH="'"$bin"':$PATH" GPU_PROC_ROOT="'"$fakeproc"'" files/usr/libexec/atomic-hyprland/waybar/gpu | jq -e ".class == \"critical\""'
check bash -c 'GPU_PROC_ROOT="$(mktemp -d)" files/usr/libexec/atomic-hyprland/waybar/gpu | jq -e ".text and .tooltip"'   # no card: CPU path, still JSON
check bash -c 'grep -q "^include=/usr/share/atomic-hyprland/mako/core.ini" files/usr/share/atomic-hyprland/themed/mako.ini.tpl'
check bash -c 'tail -n 3 files/usr/share/atomic-hyprland/themed/mako.ini.tpl | grep -q "^include=~/.config/mako/local"'
for u in waybar mako swaybg hypridle; do
  check grep -q '^WantedBy=graphical-session.target' files/usr/lib/systemd/user/$u.service
  check grep -q '^PartOf=graphical-session.target' files/usr/lib/systemd/user/$u.service
done
check grep -q 'current/background' files/usr/lib/systemd/user/swaybg.service
check grep -q 'ConditionPathExistsGlob=/sys/class/power_supply/BAT' files/usr/lib/systemd/user/atomic-hyprland-battery.service
check bash -c '! grep -qE "waybar|swaybg|hypridle|mako" files/usr/share/atomic-hyprland/hypr/autostart.lua'
```

Smoke additions (RED against the previous image): `check rpm -q mako libnotify`; for each unit `check test -L /etc/systemd/user/graphical-session.target.wants/$u.service`; `check test -L /etc/skel/.config/mako/config`; `check test "$(readlink /etc/skel/.config/mako/config)" = "../atomic-hyprland/current/theme/mako.ini"` (relative symlink so it works in any HOME); `check bash -c '! test -e /etc/skel/.config/waybar/config'`; `check test -f /etc/skel/.config/waybar/config.jsonc`; and, after a render as `nobody` in the existing `verify_hypr` HOME, `check grep -q "@define-color accent #39ff14" "$HOME/.config/atomic-hyprland/current/theme/waybar.css"`.

- [ ] **Step 2: Run both to verify they fail**

Run: `bash tests/test-waybar.sh` → FAIL (files missing); smoke against the previous image → the new lines FAIL.

- [ ] **Step 3: Write the files**

Glyphs: wifi `󰤨`/`󰤯` by signal, ethernet `󰈀`, disconnected `󰤮`; volume `󰕾`/`󰖀`/`󰕿`, muted `󰝟`; cpu `󰍛`; memory `󰘚`; gpu `󰢮`; battery `󰁺…󰁹` by level, charging `󰂄`; bluetooth `󰂯`/`󰂲`; idle `󰅶` on / `󰾪` off; notifications `󰂚`/`󰂛`; power `󰐥`; tray drawer toggle `󰅀`. Tooltips carry the words: `"tooltip-format": "cpu {usage}%  {avg_frequency} GHz"` etc. `on-click`: pulseaudio → `pavucontrol`, network → `nm-connection-editor`, cpu/memory → `ghostty -e btop`, bluetooth → `ghostty -e bluetoothctl`. The `gpu` script reads `${GPU_PROC_ROOT:-/proc}/driver/nvidia/version` to decide the path (test seam). CSS: `* { font-family: "JetBrainsMono Nerd Font"; font-size: 12px; min-height: 0; }`, `#waybar { background: @background; color: @foreground; border: 1px solid @surface; border-radius: 3px; }`, modules `margin: 0 9px`, `#workspaces button { color: @foreground_dim } button.occupied { color: @foreground } button.active { background: @accent; color: @background; border-radius: 2px }`, state classes as in the spec.

- [ ] **Step 4: Run the host test**

Run: `bash tests/test-waybar.sh` → all `ok`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(desktop): quiet waybar, mako, swaybg and hypridle as session units

New packages: mako, libnotify."
```

---

### Task 6: Launcher, power menu, lock screen, terminals, btop

**Files:**
- Create: `files/etc/skel/.config/wofi/config`, `files/etc/skel/.config/wofi/style.css` (`@import "../atomic-hyprland/current/theme/wofi.css"; … @import "local.css";`), `files/etc/skel/.config/wofi/local.css`; `files/usr/share/atomic-hyprland/themed/wofi.css.tpl`
- Create: `files/usr/bin/hypr-power` (bash: `printf '󰌾 lock\n󰒲 suspend\n󰍃 logout\n󰜉 reboot\n󰐥 shutdown\n' | wofi --show dmenu --prompt power --width 300 --lines 5 --style ~/.config/wofi/style.css`, dispatch on the word; logout = `uwsm stop`)
- Create: `files/etc/skel/.config/hypr/hyprlock.conf` (`source = ~/.config/atomic-hyprland/current/theme/hyprlock.conf`, `source = ~/.config/hypr/hyprlock.local.conf`, background `path = ~/.config/atomic-hyprland/current/background`, `blur_passes = 0`, clock/date/input as the spec pins), `files/etc/skel/.config/hypr/hyprlock.local.conf`; `files/usr/share/atomic-hyprland/themed/hyprlock.conf.tpl` (`$accent = rgb({{ accent_strip }})` etc.)
- Create: `files/etc/skel/.config/ghostty/config` (`font-family = JetBrainsMono Nerd Font`, `font-size = 11`, `window-padding-x = 8`, `window-padding-y = 8`, `config-file = ?~/.config/atomic-hyprland/current/theme/ghostty.conf`, `config-file = ?~/.config/ghostty/local`), `files/etc/skel/.config/ghostty/local`; `files/usr/share/atomic-hyprland/themed/ghostty.conf.tpl` (`background`, `foreground`, `selection-*`, `cursor-color`, `palette = 0=#…` … 15)
- Create: `files/etc/skel/.config/alacritty/alacritty.toml` (`[general] import = ["~/.config/atomic-hyprland/current/theme/alacritty.toml", "~/.config/alacritty/local.toml"]`, font, padding), `files/etc/skel/.config/alacritty/local.toml`; `files/usr/share/atomic-hyprland/themed/alacritty.toml.tpl` (`[colors.primary]`, `[colors.normal]`, `[colors.bright]`, selection, cursor)
- Create: `files/etc/skel/.config/btop/btop.conf` (`color_theme = "current"`, `theme_background = False`), `files/etc/skel/.config/btop/themes/current.theme` (symlink → `../../atomic-hyprland/current/theme/btop.theme`); `files/usr/share/atomic-hyprland/themed/btop.theme.tpl`
- Create: `tests/test-skel-includes.sh` (host)
- Modify: `skel.local` (add `.config/wofi/local.css .config/hypr/hyprlock.local.conf .config/ghostty/local .config/alacritty/local.toml`), `skel.retired` (add `.config/wofi/style-power.css .config/wofi/style-run.css .config/hypr/scripts/sleep.sh .config/hypr/xdg-portal-hyprland .config/nwg-drawer/ .config/nwg-dock-hyprland/`), `build/packages.txt` (`btop`), `tests/image-smoke.sh`, `justfile`

**Interfaces:**
- Consumes: Task 2 keys; Task 5's `custom/power` calls `hypr-power`; Task 1 restarts nothing for these (Ghostty gets SIGUSR2, Alacritty a `touch`).
- Produces: nothing later tasks consume.

- [ ] **Step 1: Write the failing host test**

```bash
# tests/test-skel-includes.sh — every image-managed config carries its theme include and its local include, in the right order
skel=files/etc/skel/.config
check grep -qx '@import "../atomic-hyprland/current/theme/wofi.css";' $skel/wofi/style.css
check bash -c "tail -1 $skel/wofi/style.css | grep -qx '@import \"local.css\";'"
check grep -qx 'source = ~/.config/atomic-hyprland/current/theme/hyprlock.conf' $skel/hypr/hyprlock.conf
check grep -qx 'source = ~/.config/hypr/hyprlock.local.conf' $skel/hypr/hyprlock.conf
check grep -qx 'path = ~/.config/atomic-hyprland/current/background' $skel/hypr/hyprlock.conf
check grep -qx 'blur_passes = 0' $skel/hypr/hyprlock.conf
check grep -qx 'config-file = ?~/.config/atomic-hyprland/current/theme/ghostty.conf' $skel/ghostty/config
check bash -c "tail -1 $skel/ghostty/config | grep -qx 'config-file = ?~/.config/ghostty/local'"
check grep -q 'import = \["~/.config/atomic-hyprland/current/theme/alacritty.toml", "~/.config/alacritty/local.toml"\]' $skel/alacritty/alacritty.toml
check test "$(readlink $skel/btop/themes/current.theme)" = ../../atomic-hyprland/current/theme/btop.theme
check grep -qx 'color_theme = "current"' $skel/btop/btop.conf
check bash -c 'for f in .config/wofi/local.css .config/hypr/hyprlock.local.conf .config/ghostty/local .config/alacritty/local.toml .config/hypr/hypridle.local.conf .config/waybar/local.jsonc .config/waybar/local.css .config/mako/local .config/hypr/local.lua; do grep -qx "$f" files/usr/share/atomic-hyprland/skel.local || exit 1; done'
check bash -c 'for f in .config/wofi/style-power.css .config/wofi/style-run.css .config/hypr/scripts/sleep.sh .config/hypr/xdg-portal-hyprland .config/nwg-drawer/ .config/nwg-dock-hyprland/ .config/waybar/config .config/waybar/mediaplayer.py .config/hypr/conf/; do grep -qxF "$f" files/usr/share/atomic-hyprland/skel.retired || exit 1; done'
check test -x files/usr/bin/hypr-power
check bash -c 'bin=$(mktemp -d); printf "#!/bin/sh\necho \"󰌾 lock\"\n" > $bin/wofi; printf "#!/bin/sh\necho hyprlock-called > $bin/out\n" > $bin/hyprlock; chmod +x $bin/*; PATH="$bin:$PATH" files/usr/bin/hypr-power; grep -q hyprlock-called $bin/out'
# every template renders for every theme (extends Task 2's loop automatically, since hypr-theme set renders all templates)
check bash -c 'HYPR_THEME_SHARE=files/usr/share/atomic-hyprland HYPR_THEME_STATE=$(mktemp -d) HYPR_THEME_NO_APPLY=1 files/usr/bin/hypr-theme set monochrome-green'
check bash -c 's=$(mktemp -d); HYPR_THEME_SHARE=files/usr/share/atomic-hyprland HYPR_THEME_STATE=$s HYPR_THEME_NO_APPLY=1 files/usr/bin/hypr-theme set monochrome-green; grep -q "^palette = 2=#39ff14" $s/current/theme/ghostty.conf && grep -q "^\$accent = rgb(39ff14)" $s/current/theme/hyprlock.conf'
```

Smoke additions: `check rpm -q btop`; `check test -x /usr/bin/hypr-power`; `check bash -c '! rpm -q wlogout'`; after the `nobody` render: `check test -f "$HOME/.config/atomic-hyprland/current/theme/btop.theme"`.

- [ ] **Step 2: Run to verify it fails**, **Step 3: write the files**, **Step 4: run to verify it passes** (`bash tests/test-skel-includes.sh`, `bash tests/test-themes.sh` — the new templates must render for all five themes).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(desktop): themed launcher, power menu, lock screen, terminals and btop

New package: btop."
```

---

### Task 7: GTK, Qt, Flatpak, icons, cursor, fonts

**Files:**
- Create: `files/etc/skel/.config/gtk-3.0/settings.ini` (`gtk-theme-name=Adwaita-dark`, `gtk-icon-theme-name=Papirus-Dark`, `gtk-cursor-theme-name=breeze_cursors`, `gtk-font-name=Inter 10`, `gtk-application-prefer-dark-theme=1`), `files/etc/skel/.config/gtk-3.0/gtk.css` and `files/etc/skel/.config/gtk-4.0/gtk.css` (symlinks → `../atomic-hyprland/current/theme/gtk.css`); `files/usr/share/atomic-hyprland/themed/gtk.css.tpl` (`@define-color accent_color {{ accent }}; @define-color accent_bg_color {{ accent }}; @define-color accent_fg_color {{ background }};`)
- Create: `files/usr/share/atomic-hyprland/themed/kvantum.kvconfig.tpl` + `files/usr/share/atomic-hyprland/kvantum/atomic-hyprland.svg` (a copy of Kvantum's `KvFlat` SVG with the highlight colour replaced by a placeholder the engine renders into `~/.config/Kvantum/atomic-hyprland/atomic-hyprland.svg` — builder: if `kvantum-data`'s KvFlat SVG is not suitable, ship `KvGnomeDark` as the single dark theme and let `hypr-theme` only `kvantummanager --set KvGnomeDark`; ledger the ruling)
- Create: `files/etc/fonts/local.conf` (monospace → JetBrainsMono Nerd Font, sans-serif → Inter)
- Modify: `files/usr/share/atomic-hyprland/hypr/env.lua` (drop `QT_QPA_PLATFORMTHEME=qt6ct`; add `QT_STYLE_OVERRIDE=kvantum`, `QT_QPA_PLATFORM=wayland;xcb`, `XCURSOR_THEME` from `palette.cursor_theme`, `XCURSOR_SIZE=24`)
- Modify: `Containerfile` (`ARG NERD_FONT_VERSION=3.5.1`, `ARG NERD_FONT_SHA256=<sha256 of JetBrainsMono.tar.xz for that release, taken from the release's checksum file and verified locally before committing>`), `build/20-desktop.sh` (download `https://github.com/ryanoasis/nerd-fonts/releases/download/v${v}/JetBrainsMono.tar.xz`, `sha256sum -c`, extract into `/usr/share/fonts/jetbrains-mono-nerd/`, `fc-cache -f`), `build/packages.txt` (`papirus-icon-theme breeze-cursor-theme kvantum kvantum-qt5 gsettings-desktop-schemas dconf rsms-inter-fonts google-noto-emoji-color-fonts flatpak`), `renovate.json` (regex manager for `ARG NERD_FONT_VERSION` → github-releases `ryanoasis/nerd-fonts`, `extractVersionTemplate ^v(?<version>.*)$`), `tests/test-build-pins.sh` (the Nerd Font pin: ARG present, sha256 is 64 hex, script verifies with `sha256sum -c`, URL uses the ARG), `tests/image-smoke.sh`, `skel.manifest` handling (gtk files are managed), `files/usr/share/atomic-hyprland/skel.retired` (nothing new)

**Interfaces:**
- Consumes: Task 1's apply step (`gsettings`, `flatpak override`, `kvantummanager`); Task 2 `cursor_theme`.
- Produces: nothing later.

- [ ] **Step 1: Extend the failing tests**

`tests/test-build-pins.sh`: `check grep -qE '^ARG NERD_FONT_SHA256=[0-9a-f]{64}$' Containerfile`; `check grep -q 'NERD_FONT_VERSION' build/20-desktop.sh`; `check grep -q 'sha256sum -c' build/20-desktop.sh`; `check bash -c '! grep -q "checksums.txt\"" build/20-desktop.sh'` (no self-referential checksum fetch). `renovate-config-validator --strict` via `just lint-ci` must still pass. Smoke: `check rpm -q papirus-icon-theme breeze-cursor-theme kvantum kvantum-qt5 gsettings-desktop-schemas dconf rsms-inter-fonts flatpak`; `check bash -c 'fc-match "JetBrainsMono Nerd Font" | grep -q JetBrainsMono'`; `check bash -c '! fc-list | grep -q RobotoMono'`; `check test -d /usr/share/icons/Papirus-Dark`; `check test -d /usr/share/icons/breeze_cursors`; `check test "$(readlink /etc/skel/.config/gtk-4.0/gtk.css)" = ../atomic-hyprland/current/theme/gtk.css`; `check grep -q 'QT_STYLE_OVERRIDE", "kvantum"' /usr/share/atomic-hyprland/hypr/env.lua`; `check bash -c '! grep -q qt6ct /usr/share/atomic-hyprland/hypr/env.lua'`; `check grep -q JetBrainsMono /etc/fonts/local.conf`.

- [ ] **Step 2: Run** `bash tests/test-build-pins.sh` and the smoke against the previous image → the new lines FAIL.

- [ ] **Step 3: Implement.** Compute the sha256 locally: `curl -fsSL -o /tmp/claude-1000/-home-dwallace-Code-atomic-hyprland/4f0770dd-911a-4c50-92a4-24dd2795e1bd/scratchpad/JetBrainsMono.tar.xz https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/JetBrainsMono.tar.xz && sha256sum …` and compare with the release's published `SHA-256.txt` before pinning (do not extract or install it on the laptop).

- [ ] **Step 4: Run** `bash tests/test-build-pins.sh && just lint-ci` → green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(desktop): GTK, Qt, Flatpak, icons, cursor and fonts follow the theme

New packages: papirus-icon-theme, breeze-cursor-theme, kvantum, kvantum-qt5,
gsettings-desktop-schemas, dconf, rsms-inter-fonts,
google-noto-emoji-color-fonts, flatpak. New pinned download: JetBrainsMono
Nerd Font v3.5.1 (replaces RobotoMono)."
```

---

### Task 8: SDDM greeter theme

**Files:**
- Create: `files/usr/share/sddm/themes/atomic-hyprland/{Main.qml,metadata.desktop,theme.conf.tpl}` (QML: full-screen background `Image` from `theme.conf` `background=`, centred column: clock `Text` (`JetBrainsMono Nerd Font`, 64 px, `%H:%M`), date (18 px, dim), user name `Text` prefilled from `userModel.lastUser`, one `TextField` password with 1 px accent border radius 3, `Keys.onReturnPressed: sddm.login(user, password, sessionIndex)`; session `ComboBox` bottom-right; power buttons bottom-left (`sddm.powerOff()`, `sddm.reboot()`, `sddm.suspend()`); no `VirtualKeyboard` import)
- Create: `files/etc/sddm.conf.d/10-atomic-hyprland.conf` (`[Theme] Current=atomic-hyprland`, `[General] InputMethod=`, `[Autologin]` absent, `[Wayland]`/`[X11]` untouched; `Session=hyprland-uwsm.desktop` under `[Autologin]` is **not** set; set `[General] DefaultSession=hyprland-uwsm.desktop`)
- Modify: `build/20-desktop.sh` (render `theme.conf.tpl` from the default theme's `colors.toml` with `hypr-theme render <tpl> <colors.toml>` (Task 1) into `/usr/share/sddm/themes/atomic-hyprland/theme.conf`, `background=/usr/share/atomic-hyprland/themes/monochrome-green/backgrounds/00-plain.png`)
- Modify: `tests/image-smoke.sh`, `files/usr/share/atomic-hyprland/skel.retired` (nothing), remove any `abstractdark` reference (`grep -rn abstractdark files/ build/` → none)

**Interfaces:**
- Consumes: Task 2 default theme and wallpaper; Task 1 renderer.
- Produces: nothing later.

- [ ] **Step 1: Smoke lines (RED against the previous image)**

```bash
check test -f /usr/share/sddm/themes/atomic-hyprland/Main.qml
check test -f /usr/share/sddm/themes/atomic-hyprland/theme.conf
check grep -q '^background=/usr/share/atomic-hyprland/themes/monochrome-green/backgrounds/00-plain.png' /usr/share/sddm/themes/atomic-hyprland/theme.conf
check grep -q '^accent=#39ff14' /usr/share/sddm/themes/atomic-hyprland/theme.conf
check grep -qx 'Current=atomic-hyprland' /etc/sddm.conf.d/10-atomic-hyprland.conf
check grep -qx 'InputMethod=' /etc/sddm.conf.d/10-atomic-hyprland.conf
check grep -qx 'DefaultSession=hyprland-uwsm.desktop' /etc/sddm.conf.d/10-atomic-hyprland.conf
check bash -c '! grep -rq abstractdark /etc/sddm.conf.d /usr/share/atomic-hyprland'
check bash -c '! grep -q VirtualKeyboard /usr/share/sddm/themes/atomic-hyprland/Main.qml'
check bash -c '! test -e /etc/sddm.conf.d/10-theme.conf'
```

- [ ] **Step 2: Run against the previous image** → FAIL. **Step 3: Write the theme and config.** **Step 4:** `qmllint` is not in the image; the gate is the hypr-test screenshot in Task 11. Verify locally what can be verified: `python3 -c "import configparser; c=configparser.ConfigParser(); c.read('files/etc/sddm.conf.d/10-atomic-hyprland.conf'); assert c['General']['InputMethod']==''"`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(sddm): minimal greeter theme from the default palette, no virtual keyboard"
```

---

### Task 9: Chromium with the Claude extension replaces Firefox

**Files:**
- Create: `files/etc/chromium/policies/managed/10-atomic-hyprland.json` (strict JSON: `{"ExtensionInstallForcelist": ["fcoeoabgfenejglbffodgkkbkcdhcgfn;https://clients2.google.com/service/update2/crx"], "BrowserColorScheme": 2, "BrowserThemeColor": "#0a0a0a"}`; the colour is the default palette's `background`)
- Modify: `build/packages.txt` (`chromium`), `files/usr/share/atomic-hyprland/hypr/env.lua` (`hl.env("BROWSER", "chromium-browser")`), `build/90-cleanup.sh` (unchanged: it already removes the base's Firefox RPM), `tests/image-smoke.sh`, `tests/test-skel-includes.sh` (one policy check)
- Control repo (separate PR in ansible-homelab-cfg, worktree off `origin/main`, same branch-name convention): `inventories/lab/group_vars/hypr_desktops/flatpaks.yml` drops `org.mozilla.firefox`; the flatpak task does not uninstall, so note in the PR that `flatpak uninstall org.mozilla.firefox` is a one-off by hand on hypr-test and the Alienware.

**Interfaces:**
- Consumes: Task 4's `binds.lua` browser binding (`chromium-browser`).
- Produces: nothing later.

- [ ] **Step 1: Failing checks**

Host (`tests/test-skel-includes.sh`): `check jq -e '.ExtensionInstallForcelist[0] == "fcoeoabgfenejglbffodgkkbkcdhcgfn;https://clients2.google.com/service/update2/crx" and .BrowserColorScheme == 2 and .BrowserThemeColor == "#0a0a0a"' files/etc/chromium/policies/managed/10-atomic-hyprland.json`; `check grep -q 'hl.env("BROWSER", "chromium-browser")' files/usr/share/atomic-hyprland/hypr/env.lua`; `check grep -q 'browser *= *"chromium-browser"' files/usr/share/atomic-hyprland/hypr/binds.lua`.
Smoke: `check rpm -q chromium`; `check test -x /usr/bin/chromium-browser`; `check jq -e . /etc/chromium/policies/managed/10-atomic-hyprland.json`; `check bash -c '! rpm -q firefox'` (already present; keep).

- [ ] **Step 2: Run** `bash tests/test-skel-includes.sh` → the new lines FAIL. **Step 3: Implement.** **Step 4: Run** → `ok`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(desktop): Chromium with the Claude extension replaces Firefox

New package: chromium (Fedora). Extension fcoeoabgfenejglbffodgkkbkcdhcgfn
force-installed by managed policy; Firefox Flatpak removed from the control
repo's list in a companion PR."
```

---

### Task 10: Milestone build 2, full suite, README and vault

**Files:**
- Modify: `README.md` (new section "Look and themes": the engine, `hypr-theme` commands, file ownership rules with the `local` list, the shipped themes, how to add a user theme; update "Local loop", the VM runbook's screenshot expectations, the Alienware notes: `local.lua` scale; remove Nord/role references; note the role is no longer consumed), `docs/superpowers/plans/…` untouched
- Modify: `~/Notebook/Projects/Atomic Hyprland/Tasks/Fix SDDM Theme and Default Wallpaper.md` → `status: Done` with a line pointing at this work; `Fix Deprecated Hyprland Options in the Role.md` → `Done` (the options are no longer emitted; the role itself is unchanged and no longer used); `Decide on nwg-dock-hyprland.md` note that the dock is out of the image by this change; `Add Chromium with the Claude Extension.md` → `Done`; `Decide GUI Apps RPM vs Flatpak.md` → `Done` (browser RPM, the rest Flatpak); `Project Overview.md` Current Focus

- [ ] **Step 1: Build and run everything**

Run: `just build && just test 2>&1 | tee /tmp/claude-1000/-home-dwallace-Code-atomic-hyprland/4f0770dd-911a-4c50-92a4-24dd2795e1bd/scratchpad/test-m2.log | grep -E "^FAIL|VERIFY_EXIT" ; just lint-ci; just lint`
Expected: zero `FAIL`, five `VERIFY_EXIT=0`, `bootc container lint` clean, renovate config valid, actionlint clean. Fix anything red before writing docs (each fix is a RED→GREEN on the owning test).

- [ ] **Step 2: Write the README section and update the vault notes**

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: describe the theme engine, file ownership and the new look"
```

---

### Task 11: Gate on hypr-test, then the Alienware

**Files:** none in the repo (operational). Record outcomes in the ledger.

- [ ] **Step 1: Publish a dev tag and switch hypr-test**

`gh workflow run build.yml --ref dw/look-theme-engine`; wait for the `dev-dw-look-theme-engine` tag; on hypr-test (via `ssh -J dwallace@10.10.99.4 dwallace@192.168.70.14`, bash -c wrappers, sudo works): `sudo bootc switch --enforce-container-sigpolicy ghcr.io/danmwallace/atomic-hyprland:dev-dw-look-theme-engine && sudo systemctl reboot`.
Expected: boots; `systemctl --failed` empty; `systemctl --user -M dwallace@ list-units 'atomic-hyprland-*'` shows the theme unit `inactive (dead)` with `Result=success` after a graphical login.

- [ ] **Step 2: Greeter screenshot**

`virsh -c qemu:///system screenshot hypr-test /tmp/greeter.png` on srv01 (wake with `send-key KEY_LEFTSHIFT`); `scp` it back and `Read` it.
Expected: near-black background, clock, name, one green-bordered field, **no keyboard overlay**.

- [ ] **Step 3: Session screenshot**

Temporary `/etc/sddm.conf.d/99-autologin-test.conf` as in earlier phases, `systemctl reset-failed sddm; systemctl restart sddm`, screenshot after 20 s.
Expected: floating bar with workspaces, clock, quiet glyph row; a Ghostty window (bind SUPER+T via `hyprctl dispatch exec ghostty` over SSH with the instance signature) with a green border; `makoctl` test notification (`notify-send test`) appears top-right under the bar. Then `hypr-theme set tokyo-night` over SSH with the signature exported: screenshot shows blue accents without a logout; `hypr-theme set monochrome-green` back. Remove the autologin file.

- [ ] **Step 4: Old-home behaviour**

hypr-test's home predates this image: `ls ~/.config/waybar/` shows `config.jsonc local.jsonc local.css style.css` and no `config`; `~/.config/hypr/conf` gone; `local.lua` unchanged (compare with the copy taken before the switch).

- [ ] **Step 5: Merge and let the Alienware take it**

Finishing-a-development-branch → PR → merge when green. The Alienware's nightly `bootc upgrade` stages `44`; Dan reboots at the laptop, enters the LUKS passphrase, checks the greeter and session, and adjusts `local.lua` (scale) if wanted. Over SSH afterwards: `cat /proc/cmdline` now has the three NVIDIA kargs (first bootc-driven deploy), `systemctl --failed` empty, `hypr-theme current` = `monochrome-green`.
