-- Dan's displays, matched by EDID description; anything else gets the
-- fallback below. Per-machine changes (scale, position) go in local.lua.
hl.monitor({ output = "desc:BOE 0x0BCA",                            mode = "2256x1504@60",  position = "auto-left",  scale = 2 })
-- LG OLED TV: 4K at 120 Hz, scale 1.5 (a 2560x1440 desktop). VRR only for
-- fullscreen apps (2): always-on VRR makes OLEDs flicker as the desktop's
-- refresh rate swings. 10-bit for smoother gradients; if screen sharing or
-- screenshots misbehave on NVIDIA, set bitdepth = 8 for it in local.lua.
hl.monitor({ output = "desc:LG Electronics LG TV SSCR2 0x01010101", mode = "3840x2160@120", position = "auto-right", scale = 1.5, vrr = 2, bitdepth = 10 })
hl.monitor({ output = "desc:Pixio USA PX277 Pro 0x00000001",       mode = "2560x1440@144", position = "auto-right", scale = 1 })
-- Anything else picks a scale from its size and resolution.
hl.monitor({ output = "",                                          mode = "preferred",     position = "auto",       scale = "auto" })

-- Apps still on XWayland render at full resolution rather than at 1x and
-- upscaled (soft at 1.5); games get the panel's native resolution too.
hl.config({ xwayland = { force_zero_scaling = true } })
