ostreecontainer --url=/run/install/repo/container --transport=oci
rootpw --lock
lang en_US.UTF-8
keyboard us
timezone UTC
clearpart --all
network --device=link --bootproto=dhcp --onboot=on --activate
%post --erroronfail
set -e
bootc switch --mutate-in-place --transport registry ghcr.io/danmwallace/atomic-hyprland:44
# used during automatic image testing as finished marker
if [ -c /dev/ttyS0 ]; then
  # continue on errors here, because we used to omit --erroronfail
  echo "Install finished" > /dev/ttyS0 || true
fi
%end
