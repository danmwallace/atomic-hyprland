include=/usr/share/atomic-hyprland/mako/core.ini
background-color={{ background_alt }}
text-color={{ foreground }}
border-color={{ accent }}
progress-color=over {{ surface }}
# Your overrides (mako allows include= only in the global section, so yours
# win for global options; add your own [urgency=...] sections in a user
# template override under ~/.config/atomic-hyprland/themed/ if needed).
include=~/.config/mako/local
[urgency=low]
text-color={{ foreground_dim }}
border-color={{ surface }}
[urgency=critical]
border-color={{ critical }}
