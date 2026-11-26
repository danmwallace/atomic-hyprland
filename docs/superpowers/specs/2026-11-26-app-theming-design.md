# Apps follow the desktop theme: Helix, Chromium, Vesktop (design)

Status: **draft for Dan's review** (2026-11-26). Calls I made are marked *(my call)*. A fresh-context builder check ran; its findings are folded in and marked *(builder check)*. Chromium's approach is waiting on Dan (section 3).

## Intent

`hypr-theme set <name>` recolors the terminals, the bar, notifications, the launcher, the lock screen, Hyprland, GTK, Qt (Kvantum) and the OpenRGB lighting. Three apps Dan uses every day don't follow:
- **Helix**, his editor. It's worse than not following. Fedora splits Helix into `helix`, `helix-themes` and `helix-parsers`, and the image installs only `helix`. So Helix has **no themes**: it logs `failed to load theme 'nord-night' - File not found` and uses its plain built-in look. It also has **no syntax highlighting**: `hx --health` shows highlight queries ✘ for every language. *(builder check)*
- **Chromium**, whose frame is pinned to `#0a0a0a` by the image's managed policy.
- **Vesktop** (Discord), which has no theme at all.

Dan's words: "We don't have to make custom themes - just maybe find something that exists that is close enough." He chose approach A (below).

## Goals

1. After `hypr-theme set <name>`, Helix, Chromium and Vesktop look like `<name>`. Each app uses an **existing** theme: the official port where one exists, otherwise the closest existing option.
2. Helix's themes and syntax highlighting are actually available on the image.
3. New machines get this with no setup. Existing setups need at most one documented one-time step per app.

## Non-goals

- Obsidian. Dan's call: it stays manual. Its theme lives in the vault's `.obsidian/`, which Syncthing shares across every machine, so switching it on one laptop would switch it everywhere.
- Slack, Spotify, Zed, Thunderbird, LibreOffice.
- Writing new themes from `colors.toml`.

## Anti-goals

- Overwriting a user's own app config. Helix's `config.toml` is Dan's file; the image only writes files it owns.
- A theme switch that breaks or restarts a running app, or loses its unsaved state.
- An unpinned download in the image build. The repo rule: binaries and data fetched outside dnf are pinned by sha256.

## Constraints

- **The theme engine:**
  - Each theme is `themes/<name>/` with `colors.toml` (a fixed key set enforced by `tests/test-themes.sh`), `icons.theme` and `backgrounds/`.
  - Hooks in `/usr/share/atomic-hyprland/hooks/theme-set.d/` run on every switch and at login, with the theme name as `$1`. A user turns one off with an empty, non-executable file of the same name in `~/.config/atomic-hyprland/hooks/theme-set.d/`.
  - The rendered theme is at `~/.config/atomic-hyprland/current/theme/`.
- **Theme folders:** shipped themes are `files/usr/share/atomic-hyprland/themes/<name>/`; user themes and overlays are `~/.config/atomic-hyprland/themes/`. An overlay of a shipped theme inherits the shipped `apps.toml`, because the engine copies the shipped folder first. *(builder check)*
- **Themes to map (17):** catppuccin-mocha, dracula, everforest, gruvbox-dark, kanagawa, monochrome-{amber,blue,cyan,green,magenta,orange,red,violet}, neon-night, nord, rose-pine, tokyo-night. Plus user themes: a theme without the new mapping must still switch cleanly (fallback below).
- **Helix 25.07.1** (Fedora). It searches its runtime in `~/.config/helix/runtime`, then `/usr/lib64/helix/runtime`. Checked 2026-11-26: `helix-themes` 25.07.1-13 installs every mapped theme and `base16_terminal` into `/usr/lib64/helix/runtime/themes/`, and `helix-parsers` installs the highlight queries for 279 languages. A running `hx` reloads its config and theme on `SIGUSR1` (verify early).
- **Chromium** is from Fedora. Its policy is `files/etc/chromium/policies/managed/10-atomic-hyprland.json`, with `BrowserColorScheme: 2` and `BrowserThemeColor: "#0a0a0a"`. Tests check it in `tests/test-skel-includes.sh`.
- **Vesktop** is the Flathub `dev.vencord.Vesktop`. Its settings live in `~/.var/app/dev.vencord.Vesktop/config/vesktop/settings/settings.json`, currently `themeLinks: []`, `enabledThemes: []`, `useQuickCss: true`.

## Approaches

- **A. Map each desktop theme to a real theme in each app** (chosen by Dan). Each theme names its counterpart per app, and a hook applies it on every switch. Themes without a port fall back to something that follows the palette.
- **B. Follow the palette everywhere:** Helix always on `base16_terminal`, Chromium on GTK, Vesktop always on one recolored theme. Less to maintain, but Tokyo Night, Nord and the rest look generic instead of like their real ports.
- Writing our own theme per app from `colors.toml` was ruled out by Dan.

## Design

### 1. The mapping: one new file per theme

- **`files/usr/share/atomic-hyprland/themes/<name>/apps.toml`** *(my call; same idea as `icons.theme`)*:
  ```toml
  helix = "tokyonight"
  vesktop = "https://…/tokyo-night.theme.css"   # a pinned raw URL (see 4)
  ```
- `tests/test-themes.sh` (host-side) requires `apps.toml` with both keys in every shipped theme. Whether each `helix` value names a theme that ships in the image is checked in `tests/image-smoke.sh`, inside the built image, because the theme files aren't in the repo. *(builder check)*
- **A theme without `apps.toml`** (a user theme): Helix gets `base16_terminal`, and Vesktop gets no theme link. Nothing fails.

### 2. Helix

- **Install `helix-themes` and `helix-parsers`** from Fedora: two lines in `build/packages.txt`. They always match the `helix` package's version, so there's no download to pin and no Renovate entry. They also turn on syntax highlighting. *(builder check; it replaces the earlier pinned-tarball idea)*
- **Hook `40-helix`:**
  - writes `~/.config/helix/themes/atomic-hyprland.toml` containing only `inherits = "<mapped theme>"`, a file the image owns;
  - then sends `SIGUSR1` to the user's running `hx` processes, so open editors switch without losing anything.
- **The one-time step:** Helix uses this only when its config says `theme = "atomic-hyprland"`.
  - A new user gets that from a skel default `~/.config/helix/config.toml` (`skel.local`: created once, never rewritten).
  - On Dan's machines it's a one-line edit, replacing `nord-night`.
  - The image never edits an existing `config.toml`.
- **Monochrome themes and neon-night** map to `base16_terminal`, which draws from the terminal's 16 colors. Those already come from the theme, so it matches exactly.

| Desktop theme | Helix |
|---|---|
| catppuccin-mocha | catppuccin_mocha |
| dracula | dracula |
| everforest | everforest_dark |
| gruvbox-dark | gruvbox |
| kanagawa | kanagawa |
| nord | nord |
| rose-pine | rose_pine |
| tokyo-night | tokyonight |
| monochrome-*, neon-night | base16_terminal |

The exact names come from the shipped theme folder; the test pins them.

### 3. Chromium, by theming GTK properly (Dan chose option 1, 2026-11-26)

Today `gtk.css.tpl` sets only libadwaita's accent colors, and GTK3 is plain Adwaita-dark, which ignores them. So GTK windows and Chromium's GTK mode look the same under every theme. The fix themes GTK itself, and Chromium follows:

- **Install `adw-gtk3-theme`** (Fedora, 6.5) and make `hypr-theme` set `gtk-theme` to `adw-gtk3-dark` instead of `Adwaita-dark`. adw-gtk3 is the existing GTK3 port of libadwaita's look, and it reads libadwaita's named colors. So one `gtk.css` themes both GTK versions: `~/.config/gtk-3.0/gtk.css` and `gtk-4.0/gtk.css` already link to the rendered theme file.
- **Widen `gtk.css.tpl`** from accent-only to libadwaita's main named colors:
  - `window_bg_color` / `window_fg_color`;
  - `view_bg_color` / `view_fg_color`;
  - `headerbar_bg_color` / `headerbar_fg_color`;
  - `card_bg_color`;
  - `popover_bg_color`;
  - `sidebar_bg_color`;
  - the accent trio already there.

  They're filled from `colors.toml`'s existing keys (`background`, `background_alt`, `surface`, `foreground`, `accent`, …), with no new keys. This maps the palette onto an existing theme; it isn't a custom theme.
- **Chromium:** remove `BrowserThemeColor` from the managed policy, keeping `BrowserColorScheme: 2`. In GTK mode, Chromium takes its frame, tab and omnibox colors from GTK3, which now follows the theme.
  - **New profiles:** patch Fedora's `/etc/chromium/master_preferences` to start in GTK mode, keeping Fedora's other entries.
  - **Existing profiles:** a one-time toggle, Settings → Appearance → Mode: GTK.
- **The effect beyond Chromium:** every GTK app's windows, headerbars and sidebars now take the theme's colors (Nautilus, Boxes, Remmina, file pickers). That's the intended "overall theming". It's also the visible risk, so Verify early 2 checks readability under all 17 themes.
- **Flatpak GTK3 apps** need the theme inside their sandbox: the Flathub extension `org.gtk.Gtk3theme.adw-gtk3-dark`. It belongs in Ansible's `desktop_flatpaks`, not the image (*my call*; it's per-user app setup). Flatpak libadwaita apps already read `gtk.css` through the existing override.
- **Live switching:** GTK apps re-read `gtk.css` when the GTK theme setting changes, not when the file changes. If that holds, `hypr-theme apply` nudges the setting (set it away and back) after writing the new `gtk.css`. Verify early 2.

### 4. Vesktop: community themes by URL (revised by the builder check)

**What it does:** the hook owns one file, `~/.var/app/dev.vencord.Vesktop/config/vesktop/themes/atomic-hyprland.css`. That file `@import`s the mapped port's pinned URL and, for monochrome and neon-night, sets the accent variable. It never edits Vencord's `settings.json` or the user's Quick CSS, which are the user's files. **The one-time step** is to enable "atomic-hyprland" under Settings → Themes → Local themes. Vencord watches its local `themes/` folder, so a changed file should apply **live** while Vesktop runs, which matters because Vesktop starts at login and sits in the tray (Verify early 3). *(my call, from the builder check)*

The original draft follows for reference; the rest of this section uses the revised mechanism.

- Each mapped theme names the official port's raw CSS URL, pinned to a commit or tag, never a branch. These are the Catppuccin, Dracula, Nord, Tokyo Night, Rosé Pine, Gruvbox, Everforest and Kanagawa Discord themes.
- Monochrome themes and neon-night use one dark theme that exposes an accent variable, such as Midnight. Its accent is set from `colors.toml`'s `accent` through Vesktop's Quick CSS. That's one variable, not a theme.
- **Hook `41-vesktop`:** writes `themes/atomic-hyprland.css` (an `@import` of the mapped URL plus, if needed, an accent variable). That's the only file it touches. If Verify early 3 shows Vencord doesn't reload local themes live, the theme lags until Vesktop restarts. That's accepted; the hook never restarts Vesktop.
- **New third-party sources:** the theme URLs are loaded by Vesktop at run time, not baked into the image. Dan approved using existing community themes. The PR lists every URL.

## Verify early

1. **Helix:**
   - that `SIGUSR1` reloads the config *and* a changed `inherits` target in 25.07.1;
   - that `base16_terminal` looks right under a monochrome theme.

   The packages are confirmed to install the themes and queries into the searched folder.
2. **GTK and Chromium**, on frmwrk:
   - with `adw-gtk3-dark` and the widened `gtk.css`, do Chromium's GTK mode (frame, tabs, omnibox) and a GTK3 and a GTK4 app take the theme's colors?
   - is text readable under all 17 themes? Check the `foreground` / `background_alt` / `surface` contrast.
   - does a switch apply live (GTK apps and Chromium), or need the setting nudge or an app restart?
3. **Vesktop:** whether Vencord reloads a changed local theme file live, and whether an `@import` of a remote URL inside a local theme file is allowed. Remote imports may be blocked by Vesktop's CSP; if so, ship the theme's CSS text, pinned, instead of importing it.
4. **The Vesktop theme URLs:** that each port has a pinnable raw CSS URL and works in current Discord.

## Left to the builder

- The exact hook numbers and names.
- How the hook finds `hx` processes (`pkill -USR1 -u "$USER" -x hx` is fine).
- The shape of the Helix release download (source tarball vs the release archive's runtime), as long as it's version-matched and pinned.
- The wording of the one-time steps in the README.
