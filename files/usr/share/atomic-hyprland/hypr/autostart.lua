-- Session plumbing only. The bar, notifications, wallpaper and idle daemon
-- are systemd user units bound to graphical-session.target (uwsm starts it).
hl.on("hyprland.start", function()
  hl.exec_cmd("gnome-keyring-daemon --start --components=secrets")
  hl.exec_cmd("dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP")
  hl.exec_cmd("systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XDG_CURRENT_DESKTOP")
  hl.exec_cmd("systemctl --user start xdg-desktop-portal-hyprland")
  hl.exec_cmd("systemctl --user start xdg-desktop-portal-gtk")
  hl.exec_cmd("systemctl --user start hyprpolkitagent")
  hl.exec_cmd("nm-applet --indicator")
  hl.exec_cmd("wl-paste --watch cliphist store")
end)
