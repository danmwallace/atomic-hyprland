/* Rendered by hypr-theme; ~/.config/wofi/style.css links here. wofi hands its
   stylesheet to GTK as a string, so this file has no relative imports: colours
   are inlined and your overrides are imported by absolute path at the end. */

* {
  font-family: "JetBrainsMono Nerd Font", monospace;
  font-size: 13px;
}

/* Obsidian glass: a deep translucent fill over Hyprland's blur (rules.lua),
   a faint lit edge, and the accent only where the eye should go. */
window {
  background-color: rgba({{ background_alt_rgb }}, 0.72);
  background-image: linear-gradient(160deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0) 45%);
  border: 1px solid rgba({{ foreground_rgb }}, 0.14);
  border-radius: 3px;
  box-shadow: inset 0 1px rgba(255, 255, 255, 0.06);
}

#outer-box, #inner-box, #scroll {
  margin: 0;
  background-color: transparent;
}
#outer-box {
  padding: 8px;
}

#input {
  margin: 0 0 8px 0;
  padding: 6px 10px;
  border: 1px solid rgba({{ foreground_rgb }}, 0.12);
  border-radius: 3px;
  background-color: rgba({{ background_rgb }}, 0.55);
  color: {{ foreground }};
  box-shadow: none;
}
#input:focus {
  border-color: {{ accent }};
}

#img {
  margin-right: 8px;
}

#entry {
  padding: 6px 10px;
  border-radius: 3px;
  color: {{ foreground_dim }};
  background-color: transparent;
}
#entry:selected {
  background-color: rgba({{ foreground_rgb }}, 0.07);
  outline: none;
}
#entry:selected #text {
  color: {{ accent }};
}
#text {
  color: inherit;
}
@import "{{ home }}/.config/wofi/local.css";
