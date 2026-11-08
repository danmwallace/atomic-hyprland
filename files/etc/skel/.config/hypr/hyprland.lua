-- atomic-hyprland entry point. Image-managed: this file is overwritten on
-- image updates, so it carries no settings of its own. Per-machine changes go
-- in local.lua (never written by the image); the look comes from the current
-- theme (hypr-theme set <name>); the defaults live in
-- /usr/share/atomic-hyprland/hypr/ and change only with the image.
package.path = "/usr/share/atomic-hyprland/hypr/?.lua;" .. package.path

-- Theme first: it defines the global `palette` the defaults read. If it has
-- not been rendered yet (first login before ensure-theme ran), fall back to
-- the default theme's colours so the session still comes up themed.
local theme_file = os.getenv("HOME") .. "/.config/atomic-hyprland/current/theme/hyprland.lua"
local ok = pcall(dofile, theme_file)
if not ok or type(palette) ~= "table" then
  palette = {
    background = "0a0a0a",
    background_glow = "171717",
    background_alt = "0c0c0c",
    surface = "2a2a2a",
    foreground = "c8c8c8",
    foreground_dim = "8a8a8a",
    accent = "39ff14",
    accent_dim = "1f8f0b",
    warning = "e0c060",
    critical = "e05050",
    selection_background = "2a2a2a",
    selection_foreground = "e0e0e0",
    color0 = "0a0a0a",
    color1 = "e05050",
    color2 = "39ff14",
    color3 = "e0c060",
    color4 = "6f8a99",
    color5 = "8a6f99",
    color6 = "6f9999",
    color7 = "c8c8c8",
    color8 = "2a2a2a",
    color9 = "e05050",
    color10 = "39ff14",
    color11 = "e0c060",
    color12 = "6f8a99",
    color13 = "8a6f99",
    color14 = "6f9999",
    color15 = "e0e0e0",
    cursor_theme = "breeze_cursors",
  }
end

-- Each require runs in its own error scope: a broken module logs and the
-- rest still load.
require("monitors")
require("env")
require("look")
require("input")
require("binds")
require("rules")
require("autostart")

-- Per-machine overrides, loaded last. Missing file is not an error.
pcall(require, "local")
