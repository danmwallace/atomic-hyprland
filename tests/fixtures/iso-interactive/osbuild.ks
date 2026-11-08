%include /run/install/repo/osbuild-base.ks
graphical

%post --erroronfail
bootc switch --mutate-in-place --enforce-container-sigpolicy --transport registry ghcr.io/danmwallace/atomic-hyprland:44
%end
