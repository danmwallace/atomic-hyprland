-- Window and layer rules. The accent border is the focus indicator, so it is
-- never suppressed; a fullscreen window simply has no border to draw.
hl.window_rule({ match = { class = "^(pavucontrol|nm-connection-editor|blueman-manager)$" }, float = true, size = "720 520", center = true })
hl.window_rule({ match = { class = "^(xdg-desktop-portal-gtk)$" }, float = true, center = true })
hl.window_rule({ match = { title = "^(Picture-in-Picture)$" }, float = true, pin = true })
