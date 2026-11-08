-- Keyboard, mouse, touchpad and gestures.
hl.config({
  input = {
    kb_layout = "us",
    follow_mouse = 1,
    mouse_refocus = true,
    float_switch_override_focus = 2,
    sensitivity = 0,
    accel_profile = "adaptive",
    touchpad = {
      natural_scroll = true,
      disable_while_typing = true,
      tap_to_click = true,
      drag_lock = false,
      tap_and_drag = true,
      scroll_factor = 1.0,
      middle_button_emulation = false,
      clickfinger_behavior = false,
    },
  },
  gestures = {
    workspace_swipe_distance = 300,
    workspace_swipe_invert = false,
    workspace_swipe_min_speed_to_force = 30,
    workspace_swipe_cancel_ratio = 0.5,
    workspace_swipe_create_new = true,
    workspace_swipe_forever = true,
  },
})

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
hl.gesture({ fingers = 3, direction = "down", mods = "ALT", action = "close" })
hl.gesture({ fingers = 3, direction = "up", mods = "SUPER", scale = 1.5, action = "fullscreen" })
