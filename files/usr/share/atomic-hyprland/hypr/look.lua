-- The look: sharp, one accent, nothing that draws attention to itself.
-- Colours come from the global `palette` (set by the rendered theme file or
-- the fallback in hyprland.lua); values are rrggbb without the #.
local function rgb(hex) return "rgb(" .. hex .. ")" end

hl.config({
  general = {
    gaps_in = 4,
    gaps_out = 8,
    border_size = 2,
    col = {
      active_border = rgb(palette.accent),
      inactive_border = rgb(palette.surface),
    },
    resize_on_border = true,
    extend_border_grab_area = 15,
    hover_icon_on_border = true,
    allow_tearing = false,
    layout = "dwindle",
  },
  decoration = {
    rounding = 3,
    active_opacity = 1.0,
    inactive_opacity = 1.0,
    fullscreen_opacity = 1.0,
    -- Blur only shows behind translucent surfaces: every window is opaque, so
    -- in practice it is the menus' obsidian glass (see rules.lua) and nothing else.
    blur = {
      enabled = true,
      size = 6,
      passes = 3,
      noise = 0.02,
      contrast = 0.9,
      brightness = 0.7,
      vibrancy = 0.0,
      popups = false,
    },
    shadow = { enabled = false },
    dim_inactive = false,
  },
  animations = { enabled = true },
  dwindle = {
    preserve_split = true,
    smart_split = false,
    smart_resizing = true,
    force_split = 0,
  },
  master = {
    new_status = "master",
    new_on_top = false,
    mfact = 0.55,
    orientation = "left",
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
    inactive_timeout = 0,
    hide_on_key_press = true,
  },
})

-- Short and quiet: 150-200 ms (speed is in 100 ms units).
hl.curve("easeOutQuint", { type = "bezier", points = { {0.23, 1}, {0.32, 1} } })
hl.curve("linear",       { type = "bezier", points = { {0, 0},    {1, 1}    } })

hl.animation({ leaf = "global",           enabled = true,  speed = 2,   bezier = "default" })
hl.animation({ leaf = "border",           enabled = false })
hl.animation({ leaf = "borderangle",      enabled = false })
hl.animation({ leaf = "windows",          enabled = true,  speed = 2,   bezier = "easeOutQuint", style = "popin 90%" })
hl.animation({ leaf = "windowsOut",       enabled = true,  speed = 1.5, bezier = "linear",       style = "popin 90%" })
hl.animation({ leaf = "windowsMove",      enabled = true,  speed = 2,   bezier = "easeOutQuint", style = "slide" })
hl.animation({ leaf = "fade",             enabled = true,  speed = 1.5, bezier = "linear" })
hl.animation({ leaf = "layers",           enabled = true,  speed = 1.5, bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "workspaces",       enabled = true,  speed = 1.8, bezier = "easeOutQuint", style = "slide" })
hl.animation({ leaf = "specialWorkspace", enabled = true,  speed = 1.8, bezier = "easeOutQuint", style = "slidevert" })
