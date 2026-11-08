%include /run/install/repo/osbuild-base.ks

autopart --nohome --type=btrfs

reboot --eject
