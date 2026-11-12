-- Key bindings. SUPER is the modifier; programs are the image's defaults.
local mod = "SUPER"
local terminal = "hypr-terminal"
local fileManager = "nautilus"
local menu = "wofi --show drun"
local browser = "chromium-browser"
local lock = "hyprlock"
local power = "hypr-power"

-- Programs start through uwsm-app: each gets its own systemd scope under the
-- session, so it is tracked, cleaned up and logged like everything else.
local function app(cmd) return hl.dsp.exec_cmd("uwsm-app -- " .. cmd) end
hl.bind(mod .. " + T",         app(terminal))
hl.bind(mod .. " + RETURN",    app(terminal))
hl.bind(mod .. " + B",         app(browser))
hl.bind(mod .. " + E",         app(fileManager))
hl.bind(mod .. " + SPACE",     app(menu))
-- The desktop agent: ask about what is on screen (see hypr-agent)
hl.bind(mod .. " + A",         hl.dsp.exec_cmd("hypr-agent ask"))
hl.bind(mod .. " + SHIFT + V", hl.dsp.exec_cmd("cliphist list | wofi --show dmenu --lines 12 | cliphist decode | wl-copy"))
hl.bind(mod .. " + SHIFT + T", hl.dsp.exec_cmd("hypr-theme bg next"))

-- Window management
hl.bind(mod .. " + C",         hl.dsp.window.close())
hl.bind(mod .. " + V",         hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + F",         hl.dsp.window.fullscreen({ action = "toggle", mode = "fullscreen" }))
hl.bind(mod .. " + SHIFT + F", hl.dsp.window.fullscreen({ action = "toggle", mode = "maximized" }))
hl.bind(mod .. " + P",         hl.dsp.window.pseudo({ action = "toggle" }))
-- Hyprland matches keys case-insensitively, so letters used by the vim focus
-- keys below (h j k l) are not reused with SUPER alone.
hl.bind(mod .. " + U",              hl.dsp.layout("togglesplit"))
hl.bind(mod .. " + ESCAPE",         hl.dsp.exec_cmd(lock))
hl.bind(mod .. " + SHIFT + ESCAPE", hl.dsp.exec_cmd(power))

-- Screenshots
hl.bind(mod .. " + SHIFT + S",     hl.dsp.exec_cmd("grim -g \"$(slurp)\" - | wl-copy && wl-paste | cliphist store"))
hl.bind(mod .. " + SHIFT + Print", hl.dsp.exec_cmd("mkdir -p ~/Pictures/Screenshots && grim -g \"$(slurp)\" ~/Pictures/Screenshots/$(date +%Y%m%d_%H%M%S).png"))
hl.bind("Print",                   hl.dsp.exec_cmd("mkdir -p ~/Pictures/Screenshots && grim ~/Pictures/Screenshots/$(date +%Y%m%d_%H%M%S).png"))

-- Focus: arrows and vim keys
for _, pair in ipairs({ { "left", "left" }, { "right", "right" }, { "up", "up" }, { "down", "down" },
                        { "h", "left" }, { "l", "right" }, { "k", "up" }, { "j", "down" } }) do
  hl.bind(mod .. " + " .. pair[1], hl.dsp.focus({ direction = pair[2] }))
end

-- Move and resize
hl.bind(mod .. " + SHIFT + left",  hl.dsp.window.move({ direction = "left" }))
hl.bind(mod .. " + SHIFT + right", hl.dsp.window.move({ direction = "right" }))
hl.bind(mod .. " + SHIFT + up",    hl.dsp.window.move({ direction = "up" }))
hl.bind(mod .. " + SHIFT + down",  hl.dsp.window.move({ direction = "down" }))
hl.bind(mod .. " + CTRL + left",   hl.dsp.window.resize({ x = -20, y = 0,   relative = true }))
hl.bind(mod .. " + CTRL + right",  hl.dsp.window.resize({ x = 20,  y = 0,   relative = true }))
hl.bind(mod .. " + CTRL + up",     hl.dsp.window.resize({ x = 0,   y = -20, relative = true }))
hl.bind(mod .. " + CTRL + down",   hl.dsp.window.resize({ x = 0,   y = 20,  relative = true }))

-- Workspaces 1..10 (key 0 = workspace 10)
for i = 1, 10 do
  local key = i % 10
  hl.bind(mod .. " + " .. key,                hl.dsp.focus({ workspace = i }))
  hl.bind(mod .. " + SHIFT + " .. key,        hl.dsp.window.move({ workspace = i, follow = true }))
  hl.bind(mod .. " + CTRL + SHIFT + " .. key, hl.dsp.window.move({ workspace = i, follow = false }))
end
hl.bind(mod .. " + W",          hl.dsp.workspace.toggle_special("magic"))
hl.bind(mod .. " + SHIFT + W",  hl.dsp.window.move({ workspace = "special:magic" }))
hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))
hl.bind(mod .. " + mouse:272",  hl.dsp.window.drag(),   { mouse = true })
hl.bind(mod .. " + mouse:273",  hl.dsp.window.resize(), { mouse = true })

-- Laptop keys: work while locked, repeat while held
hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd("pamixer -i 5"),                 { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd("pamixer -d 5"),                 { locked = true, repeating = true })
hl.bind("XF86AudioMute",         hl.dsp.exec_cmd("pamixer -t"),                   { locked = true })
hl.bind("XF86AudioMicMute",      hl.dsp.exec_cmd("pamixer --default-source -t"),  { locked = true })
hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd("brightnessctl s 5%+"),          { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl s 5%-"),          { locked = true, repeating = true })
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })

-- Lid close locks; disabling the panel for a docked setup belongs in local.lua.
hl.bind("switch:on:Lid Switch", hl.dsp.exec_cmd(lock), { locked = true })
