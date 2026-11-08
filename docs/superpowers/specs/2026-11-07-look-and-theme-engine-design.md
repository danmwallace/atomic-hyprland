# Look and theme engine — design

Date: 2026-11-07. Status: approved in conversation by Dan; builder check pending.

## Intent

The image boots to a desktop that looks finished and stays that way without
Dan tending it. Today the Hyprland config comes from the `danmwallace.fedora.hyprland`
Ansible role, rendered at image build with one baked palette (Nord). Its reach
stops at five apps, several referenced pieces are missing or broken (no
notification daemon, waybar icons lost, dead power/media modules, uninstalled
SDDM and cursor themes, no GTK/Qt theming), and changing the look means an
image rebuild. Dan's words: polished and minimal; dark monochrome with a neon
accent; "the top bar just displays numerical values without any real
indication of what they are"; what he likes about Omarchy is that it feels
complete and "applications carry the theme".

Two of Dan's three past pains (Hyprland config breaking on updates, waybar
modules rotting) are maintenance problems. The image already runs the config
through `Hyprland --verify-config` in CI on every nightly; this design keeps
that gate and extends it to the rendered theme files, so an upstream change
breaks the pipeline, not the login.

## Goals

1. One palette applied everywhere at once: Hyprland, waybar, notifications,
   launcher, lock screen, terminals (Ghostty, Alacritty), btop, GTK apps,
   Qt apps, cursor, icons, wallpaper, SDDM greeter.
2. Switching palettes at runtime in seconds, no image rebuild.
3. Shipped defaults separated from Dan's overrides so image updates never
   touch his files.
4. Every value on the bar is self-explanatory; the bar is quiet until
   something needs attention.
5. The image build no longer depends on the Ansible role; the Hyprland config
   lives in this repo.
6. CI fails on a broken rendered config for every shipped theme.

## Non-goals

- Light themes (the engine must not prevent them; none ship).
- Chromium frame colour (belongs to the "Chromium + Claude extension" task;
  the engine must leave a hook for it).
- Runtime re-theming of SDDM (it runs as root before login; it takes the
  image's default theme colours at build).
- nwg-dock, nwg-drawer (separate decision task; both dropped from the image
  by this work; the decision task can bring one back).
- Multi-monitor layouts beyond "every output at scale 1, auto-placed".
- Fixing the deprecated `special_scale_factor` options is folded in (the
  options are simply not emitted), closing that vault task.

## Anti-goals (what would make this a failure even if it works)

- A bar that needs a legend. Bare numbers, ambiguous icons, or values that
  mean nothing without hovering *and* never change colour.
- Visual noise: more than one accent colour on screen in the default theme,
  blur/shadow/animation that draws attention to itself, mixed corner radii.
- A second config tree Dan has to merge by hand after updates.
- Theme switching that leaves some app on the old palette.

## Decisions Dan made (in the brainstorm, with mockups)

| Topic | Decision |
|---|---|
| Default palette | **Monochrome + neon green**: greys from near-black to light grey, one accent `#39ff14` that does all the work; red and yellow only for warnings. |
| Other shipped palettes | monochrome-blue (accent `#3d9bff`), tokyo-night, nord, dracula. Switchable; not polished to the same depth as the default. |
| Geometry | **Sharp with a floating bar**: rounding 3 px everywhere (windows, bar, launcher, notifications, lock field), gaps 4 inside / 8 outside, solid 2 px border (accent on the focused window, dark grey on others), no blur, no shadows, animations on but short (150–200 ms). The bar floats as its own island with the same gap as the windows so bar and tiles read as one grid. |
| Bar reading | **Glyphs, quiet by default**: Nerd Font icon per module, no numbers shown; an icon turns accent for a good state (charging, idle inhibitor on) and red for attention (GPU ≥ 80 °C, battery ≤ 15 %, audio muted, network down); hover shows the full figures. Workspaces left (occupied brighter, active filled with accent), dimmed window title, clock centred, tray collapsed into a drawer, power button far right behind a thin separator. |
| Wallpaper | **Plain dark**: a near-black radial gradient, slightly lighter at the centre, no picture; shipped as an image file generated at build from the theme's colours so every palette has its own. `~/Pictures/Wallpapers`, if present, joins the rotation. |
| Greeter | Same wallpaper; clock, user name, one accent-bordered password field, session selector bottom-right, power bottom-left. **No virtual keyboard.** |
| Where it lives | The image repo. The Ansible role stays published but the image stops consuming it. |
| LiteLLM, Omarchy itself | Out of scope; not adopted (Omarchy is Arch-only; its mechanism is copied, nothing else). |

## The mechanism

Copied from Omarchy v3 (the last release with waybar/mako/hyprlock), adapted
to a read-only image where shipped files live under `/usr/share` and the
home directory is only ever written by user-owned processes.

### Shipped files (image, read-only)

```
/usr/share/atomic-hyprland/
  themes/<name>/
    colors.toml          required; see "Palette file"
    backgrounds/         ≥ 1 image; sorted; first is the default
    icons.theme          one line: icon theme name (default Papirus-Dark)
  themed/*.tpl           templates rendered per theme; see "Templates"
  hypr/*.lua             Hyprland defaults: env, input, binds, rules, look,
                         autostart, monitors (replaces the role's conf/*.lua)
  skel/                  the user-side configs that carry include lines
                         (hyprland.lua, waybar/config.jsonc, waybar/style.css,
                         mako is a symlink, wofi/*.css, ghostty/config,
                         alacritty/alacritty.toml, btop/btop.conf, hypr/hyprlock.conf,
                         hypr/hypridle.conf, gtk-3.0/settings.ini, …)
  skel.manifest          as today, consumed by sync-dotfiles
  sddm/                  the greeter theme sources (QML + rendered colours)
/usr/bin/hypr-theme      the engine (bash)
/usr/bin/hypr-power      wofi power menu (replaces wlogout)
/usr/libexec/atomic-hyprland/waybar/*   indicator scripts (return-type json)
```

### State (per user, writable)

```
~/.config/atomic-hyprland/
  current/theme/         rendered output of every template for the current theme
  current/background     symlink to the active wallpaper file
  current/theme.name     one line
  themes/<name>/         optional user overlay: files here win over the shipped
                         theme of the same name; a new name here is a new theme
  themed/*.tpl           optional user template overrides
```

### `hypr-theme` (bash, no dependencies beyond coreutils, sed, awk)

- `hypr-theme list` — shipped and user themes, current marked.
- `hypr-theme set <name>` — build `current/next-theme/` from the shipped
  theme, copy the user overlay over it, render every template (user
  `themed/` first, then shipped; a file already present in the theme dir is
  not overwritten, so a theme may ship a hand-written `btop.theme`), then
  atomically replace `current/theme/`, write `theme.name`, repoint
  `current/background` to the theme's first background unless
  `--keep-background`, and apply: `hyprctl reload`; restart waybar and mako
  (`systemctl --user restart`); `pkill -SIGUSR2 ghostty`; `touch` the
  alacritty config (it live-reloads); `gsettings set org.gnome.desktop.interface
  color-scheme prefer-dark`, `gtk-theme Adwaita-dark`, `icon-theme <icons.theme>`,
  `cursor-theme <value from colors.toml>`; `kvantummanager --set <kvantum theme>`
  if present; then run `~/.config/atomic-hyprland/hooks/theme-set.d/*` (the
  hook later used for Chromium).
- `hypr-theme bg next|set <file>` — rotate or pick a wallpaper from the
  theme's `backgrounds/` plus `~/Pictures/Wallpapers`; repoint the symlink;
  restart swaybg.
- `hypr-theme refresh` — re-render the current theme (after an image update
  changed a template) without changing wallpaper.
- `hypr-theme current` — print the name.

Rendering: every `key = "value"` in `colors.toml` yields three substitutions,
`{{ key }}` → `#1a1a1a`, `{{ key_strip }}` → `1a1a1a`, `{{ key_rgb }}` →
`26,26,26` (Omarchy's convention; keeps templates trivially portable). A
placeholder that no key satisfies is a render error, not silent text.

### Palette file (`colors.toml`)

Required keys: `background`, `background_alt` (bar/launcher surfaces),
`surface` (inactive border, separators), `foreground`, `foreground_dim`,
`accent`, `accent_dim` (hover/occupied states), `warning`, `critical`,
`selection_background`, `selection_foreground`, `cursor_theme`, and
`color0`–`color15` for the terminals. The monochrome-green default:

```
background = "#0a0a0a"     background_alt = "#0c0c0c"   surface = "#2a2a2a"
foreground = "#c8c8c8"     foreground_dim = "#8a8a8a"
accent = "#39ff14"         accent_dim = "#1f8f0b"
warning = "#e0c060"        critical = "#e05050"
selection_background = "#2a2a2a"   selection_foreground = "#e0e0e0"
cursor_theme = "breeze_cursors"
color0..15: greys for 0/7/8/15, the accent for 2/10 (green), the warning and
critical for 1/9 and 3/11, blue/magenta/cyan desaturated greys-with-a-tint so
terminal output stays readable but monochrome.
```

The builder tunes the exact grey steps and the sixteen terminal colours; the
constraint is "one accent on screen, warnings only when warning".

### Templates (`themed/*.tpl`) and the include line each app carries

| Template | App config include |
|---|---|
| `hyprland.lua.tpl` → `theme/hyprland.lua` (defines `palette` table and the border colours) | `~/.config/hypr/hyprland.lua`: `dofile(os.getenv("HOME").."/.config/atomic-hyprland/current/theme/hyprland.lua")` before the defaults |
| `waybar.css.tpl` (`@define-color` lines only) | `waybar/style.css`: `@import "../atomic-hyprland/current/theme/waybar.css";` |
| `mako.ini.tpl` (colours; `include=/usr/share/atomic-hyprland/mako/core.ini`) | `~/.config/mako/config` is a symlink to `current/theme/mako.ini` |
| `wofi.css.tpl` | `wofi/style.css`: `@import "../atomic-hyprland/current/theme/wofi.css";` |
| `hyprlock.conf.tpl` (colour variables) | `hypr/hyprlock.conf`: `source = ~/.config/atomic-hyprland/current/theme/hyprlock.conf`; background `path = ~/.config/atomic-hyprland/current/background` |
| `ghostty.conf.tpl` | `ghostty/config`: `config-file = ?~/.config/atomic-hyprland/current/theme/ghostty.conf` |
| `alacritty.toml.tpl` | `alacritty/alacritty.toml`: `[general] import = ["~/.config/atomic-hyprland/current/theme/alacritty.toml"]` |
| `btop.theme.tpl` | `btop/btop.conf`: `color_theme = "current"`; `btop/themes/current.theme` symlink |
| `gtk.css.tpl` (accent/selection only, on top of Adwaita-dark) | `gtk-3.0/gtk.css` and `gtk-4.0/gtk.css` symlinks |
| `kvantum.kvconfig.tpl` | applied by `hypr-theme set` via `kvantummanager` into a per-theme Kvantum theme directory under `~/.config/Kvantum/atomic-hyprland/` |
| `wallpaper.svg.tpl` | rendered at **build** into `themes/<name>/backgrounds/00-plain.png` for every shipped theme (ImageMagick or rsvg-convert in the build stage, not in the image); the runtime engine only symlinks |

Hyprland is Lua, so the theme file is Lua: it sets a global `palette` table
(the same keys as `colors.toml`) that the defaults in
`/usr/share/atomic-hyprland/hypr/look.lua` read. `hyprland.lua` in the home
directory is thin and stable: theme file, then `dofile` of each shipped
default, then `local.lua`. Image updates change the defaults; the two files
in the home directory never need to change (same promise as Omarchy's
`default/` directory).

### First login and image updates

`sync-dotfiles` (existing, runs from `atomic-hyprland-dotfiles.service` at
login) lays down `skel/` as today and then, if `current/theme/` is missing or
`current/theme.name` is set but the image version stamp changed, runs
`hypr-theme set "$(cat theme.name 2>/dev/null || echo monochrome-green)"
--keep-background`. The chosen theme survives updates; a template fix in a
new image is applied at the next login. `local.lua` and the user overlay are
never written by the image.

## The look, pinned

Values the builder implements as given; everything not listed is theirs.

- **Hyprland**: `general.gaps_in = 4`, `gaps_out = 8`, `border_size = 2`,
  `col.active_border = rgb(<accent_strip>)` (no gradient, no border
  animation), `col.inactive_border = rgb(<surface_strip>)`,
  `decoration.rounding = 3`, `blur.enabled = false`, `shadow.enabled =
  false`, `inactive_opacity = 1.0`, `layout = dwindle` with
  `preserve_split = true`; animations enabled, beziers `easeOutQuint`
  (0.23,1,0.32,1) and `linear`, `windows 2.0 easeOutQuint popin 90%`,
  `workspaces 1.8 easeOutQuint slide`, `fade 1.5 linear`, `layers 1.5
  easeOutQuint`, no border/borderangle animation. `misc.disable_hyprland_logo
  = true`, `force_default_wallpaper = 0`. No `special_scale_factor`.
  Cursor from `palette.cursor_theme`, size 24. Scale: every monitor
  `preferred, auto, 1`; machines override in `local.lua`.
- **Waybar** (`config.jsonc` must be strict JSON so `jq` validates it):
  `layer top`, `position top`, `height 30`, `margin-top 8`,
  `margin-left/right 8` (the floating island; 8 = `gaps_out`),
  `reload_style_on_change true`. Left: `hyprland/workspaces` (`format "{id}"`,
  persistent 1–5, `active` filled accent, occupied `foreground`, empty
  `foreground_dim`), `hyprland/window` (`max-length 60`, dim). Center:
  `clock` (`{:%a %-d %b  %H:%M}`, tooltip calendar). Right, in order:
  `group/tray-drawer` (tray collapsed behind a `󰅀` toggle), `bluetooth`,
  `network`, `pulseaudio`, `cpu`, `memory`, `temperature` (GPU via the
  `nvidia` hwmon when present, else the CPU package), `battery`, `idle_inhibitor`,
  `custom/notifications` (mako do-not-disturb state), separator, `custom/power`
  (`hypr-power`). Every right module: `format "{icon}"` or a single glyph,
  **no number in the default format**, full figures in `tooltip-format`,
  `on-click` where sensible (pavucontrol, nm-connection-editor, btop in the
  terminal), scroll on volume and brightness. Colour rules in CSS:
  `#battery.charging`, `#idle_inhibitor.activated`, `#custom-notifications.dnd`
  → accent; `#battery.critical`, `#temperature.critical` (≥ 80 °C),
  `#pulseaudio.muted`, `#network.disconnected` → `critical`;
  `#battery.warning` (≤ 30 %) → `warning`. Glyphs from the Nerd Font MDI
  range (`󰤨` wifi, `󰕾` volume, `󰍛` cpu, `󰘚` memory, `󰢮` gpu, `󰂊` battery,
  `󰐥` power, `󰂯` bluetooth, `󰅶`/`󰾪` idle, `󰂚`/`󰂛` notifications). Font
  `JetBrainsMono Nerd Font 12px`. Bar background `background_alt`, 1 px
  border `surface`, radius 3. Removed: `custom/media`, `custom/updates`,
  `backlight` in the bar (brightness stays on keys and scroll over the
  clock? no: brightness is keys only), `hyprland/submap`.
- **Mako**: `background_alt`, border 1 px accent, radius 3, width 360,
  anchor top-right, margin 12 (below the bar), default timeout 6 s,
  urgency critical → border `critical`, no timeout. Font JetBrainsMono
  Nerd Font 11.
- **Wofi**: launcher (`drun`) and `hypr-power` (lock / suspend / logout /
  reboot / shutdown with Nerd glyphs) share the geometry: radius 3, 1 px
  border accent, `background_alt`, selected row `accent` text on
  `surface`. Width 600, 8 lines.
- **Hyprlock**: `current/background` with `blur_passes = 0`, clock
  `%H:%M` large and `%A %-d %B` small in `foreground`, one input field
  with `outer_color accent`, `inner_color background_alt`, `check_color
  accent_dim`, `fail_color critical`, radius 3.
- **Hypridle**: lock at 5 min, DPMS off at 10, suspend at 20 min on
  battery only; `before_sleep` locks; lid close locks (bindl in binds).
- **Terminals**: Ghostty default terminal (`$TERMINAL`), Alacritty themed
  too. Font JetBrainsMono Nerd Font 11; padding 8.
- **GTK**: `gsettings` `color-scheme prefer-dark`, `gtk-theme Adwaita-dark`,
  `icon-theme Papirus-Dark`, `cursor-theme breeze_cursors`, `font-name
  "Inter 10"` (Fedora `rsms-inter-fonts`; builder may pick Cantarell if
  Inter proves awkward); `gtk.css` recolours `@accent_color`/`@accent_bg_color`
  only. Per-user `gtk-3.0/settings.ini` mirrors the same values for apps
  that ignore gsettings. Plasma's leftover `gtk-3.0`/`gtk-4.0` files in an
  existing home are overwritten by `sync-dotfiles` (they are image-managed
  paths now).
- **Qt**: `QT_QPA_PLATFORMTHEME=qt6ct` dropped; `QT_STYLE_OVERRIDE=kvantum`
  with packages `kvantum` and `kvantum-qt5`; a generated Kvantum theme per
  palette (dark, flat, 3 px radius, accent highlight). Builder decides whether
  to generate from a `.kvconfig`+`.svg` template or ship one dark Kvantum
  theme and only swap its highlight colour.
- **Fonts**: JetBrainsMono Nerd Font (upstream release tarball, pinned URL +
  sha256 in the Containerfile like `TUIOS_SHA256`, Renovate rule for
  `ryanoasis/nerd-fonts`), replacing RobotoMono; `rsms-inter-fonts`;
  `google-noto-emoji-color-fonts`. fontconfig: monospace → JetBrainsMono Nerd
  Font.
- **SDDM**: theme `atomic-hyprland` in `/usr/share/sddm/themes/`, QML, colours
  rendered at build from the default theme's `colors.toml`, background the
  default theme's `00-plain.png`; `/etc/sddm.conf.d/10-atomic-hyprland.conf`
  with `[Theme] Current=atomic-hyprland` and `[General] InputMethod=`
  (empty: removes the virtual keyboard). `qt6-qtvirtualkeyboard` is not
  removed (other things pull it); the empty `InputMethod` is what matters.
  Clock `%H:%M`, date, user name prefilled from the last session, one
  password field, session dropdown bottom-right, power buttons bottom-left.
- **Wallpaper**: `00-plain.png` per theme, 3840×2160, radial gradient from
  `background` lightened ~6 % at 50 %/40 % to `background` darkened ~2 % at
  the edges; `swaybg -m fill`.
- **Laptop basics** (binds and daemons): XF86 brightness keys → `brightnessctl
  s 5%±`; volume/mute keys → `pamixer`; `XF86AudioMicMute`; lid close →
  `hyprlock`; battery ≤ 15 % → one mako notification (critical) from a
  small timer script (`/usr/libexec/atomic-hyprland/battery-warn`, user timer
  every 2 min).

## What leaves

- The `danmwallace.fedora.hyprland` role from the build (`build/playbook.yml`,
  `build/requirements.yml`, `build/20-hyprland-role.sh`, the Ansible install
  in `10-packages.sh`); replaced by `build/20-desktop.sh` that installs the
  role's package list (now in `build/packages.txt`) plus the new packages,
  downloads and verifies the Nerd Font, renders the per-theme wallpapers and
  the SDDM colours, and copies nothing (files come from `files/` via `COPY`).
- `nwg-dock-hyprland`, `nwg-drawer`, `waypaper`, `hyprpaper` (swaybg stays),
  `wlogout` references, `qt6ct`, `blueman` (bluetooth stays via the waybar
  module + `bluetoothctl`; builder may keep blueman if the module's
  `on-click` needs a GUI), the dead `mediaplayer.py` reference,
  `abstractdark-sddm-theme` reference, `Nordzy-catppuccin-frappe-blue`.
- `THEME` build arg: the image ships all themes; the default is a constant
  in `hypr-theme` (`monochrome-green`).

## Tests (CI gate)

In `tests/image-smoke.sh` (runs inside the built image):

- For **every** shipped theme: render it as `nobody` into a temporary HOME
  (`hypr-theme set <name>` with `HYPR_THEME_NO_APPLY=1`, which skips the
  `hyprctl`/`systemctl`/`gsettings` steps), then `setpriv … Hyprland
  --verify-config` with that HOME → exit 0 and `config ok`; `jq -e . <
  waybar/config.jsonc`; `mako` config keys present; every `{{ … }}`
  placeholder in every template resolved (grep for `{{` in the rendered
  tree → none).
- Default theme name resolves; `theme.name` round-trips; `refresh` is a
  no-op on an unchanged theme (idempotent, compares a checksum).
- Files: SDDM theme present and `InputMethod=` empty; fonts installed
  (`fc-match "JetBrainsMono Nerd Font"`); icon and cursor themes present;
  `mako`, `kvantum`, `kvantum-qt5`, `papirus-icon-theme`,
  `breeze-cursor-theme`, `brightnessctl`, `pamixer` installed; `nwg-*`,
  `qt6ct`, `hyprpaper` absent; no `special_scale_factor` anywhere under
  `/usr/share/atomic-hyprland`.
- Host tests: `tests/test-build-pins.sh` extended for the Nerd Font
  pin; `tests/test-hypr-theme.sh` runs the renderer on the host against a
  fixture `colors.toml` (substitution forms, missing key is an error,
  overlay precedence, atomic swap leaves no `next-theme`).

Gate on hypr-test (no GPU) as before: greeter screenshot (no keyboard
overlay, correct colours) and a Hyprland session screenshot (bar island,
green border). Then the Alienware by `bootc upgrade` and a visual check by
Dan.

## Left to the builder

- Exact grey steps and terminal colour0–15 for each palette (constraint
  above); the Kvantum approach; whether Inter or Cantarell; the SDDM QML
  layout details within the pinned content; the exact MDI glyph set; the
  `wallpaper.svg.tpl` gradient numbers; how `group/tray-drawer` is built in
  waybar 0.15; whether `blueman` stays.
- Sequencing of the removal of Ansible from the build versus adding the
  engine (one branch, but order of commits is theirs).
- How `sync-dotfiles` detects "image version changed" (it already writes a
  stamp).

## Open risks

- Hyprland 0.57 Lua API: `dofile` of absolute paths from `/usr/share` must
  work inside `hyprland.lua`; the current role already `dofile`s files from
  the home directory, so this is expected to hold. If `hl.*` calls are
  scoped per file in a way that breaks a `palette` global, the theme file
  can `return` the table and defaults can `require` it instead.
- waybar 0.15's `hyprland/workspaces` and `group` module syntax; validate
  by running waybar once in the smoke test if a headless run proves
  possible (it needs a Wayland display; if not, `jq` validity + a
  manual gate on hypr-test is the fallback).
- Kvantum with Qt 6.10 on Fedora 44: if the `kvantum` package lags, fall back
  to `QT_QPA_PLATFORMTHEME=gtk3` (Adwaita-dark via the GTK platform theme),
  which still gives a dark, consistent Qt.
