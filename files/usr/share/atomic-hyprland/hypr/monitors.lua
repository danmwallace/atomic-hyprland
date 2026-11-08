-- Dan's displays, matched by EDID description; anything else gets the
-- fallback at scale 1. Per-machine changes (scale, position) go in local.lua.
hl.monitor({ output = "desc:BOE 0x0BCA",                            mode = "2256x1504@60",  position = "auto-left",  scale = 2 })
hl.monitor({ output = "desc:LG Electronics LG TV SSCR2 0x01010101", mode = "3840x2160@120", position = "auto-right", scale = 1 })
hl.monitor({ output = "desc:Pixio USA PX277 Pro 0x00000001",       mode = "2560x1440@144", position = "auto-right", scale = 1 })
hl.monitor({ output = "",                                          mode = "preferred",     position = "auto",       scale = 1 })
