# atomic-hyprland

A bootc-built Fedora Hyprland desktop image. See docs/superpowers/specs/ for the design.

## Local loop

```bash
just check-kernel   # base and akmods on the same kernel
just build          # rootless podman build, tags :44 and :44-<date>-<sha>
just test           # in-image smoke + dotfile sync tests
just push           # to ghcr.io (podman login first)
just qcow2          # sudo; output/qcow2/disk.qcow2 for the srv01 VM
```
