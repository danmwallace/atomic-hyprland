/* Rendered by hypr-theme; imported by ~/.config/swaync/style.css. swaync loads its
   own stylesheet (/etc/xdg/swaync/style.css) first; this puts the theme on top. */
:root {
  --cc-bg: {{ background_alt }};
  --noti-border-color: {{ accent }};
  --noti-bg-darker: {{ background }};
  --noti-bg-hover: {{ surface }};
  --noti-bg-focus: {{ surface }};
  --noti-close-bg: {{ surface }};
  --noti-close-bg-hover: {{ accent_dim }};
  --text-color: {{ foreground }};
  --text-color-disabled: {{ foreground_dim }};
  --bg-selected: {{ accent_dim }};
  --border-radius: 3px;
  --notification-shadow: none;
  --font-size-body: 13px;
  --font-size-summary: 13px;
}

* {
  font-family: "FiraCode Nerd Font", monospace;
}

/* swaync's own rules take the background from an RGB triplet; the theme has hex. */
.notification-row .notification-background .notification,
.notification-group.collapsed .notification-row .notification {
  background: {{ background_alt }};
}

.notification-row .notification-background .notification.low {
  border-color: {{ surface }};
}

.notification-row .notification-background .notification.low .body {
  color: {{ foreground_dim }};
}

.notification-row .notification-background .notification.critical {
  border-color: {{ critical }};
}

.control-center {
  border: 1px solid {{ surface }};
}
