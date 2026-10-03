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

## Phase 1 status (2026-10-03)

- `hypr-test` VM on srv01 (192.168.70.14) boots the image: `bootc status` shows
  `ghcr.io/danmwallace/atomic-hyprland:44`, cloud-init created `dwallace` with
  `/usr/bin/elvish`, the dotfile sync unit ran, SDDM greeter is up on Xorg.
  Verified over SSH 2026-10-03. Graphical login: see the VM runbook.
- Known gaps (deliberate, later phases): no NVIDIA, no Ollama/LiteLLM, image
  unsigned (policy allows our registry unsigned until Phase 3), the role's
  `10-theme.conf` names an SDDM theme that is not installed so SDDM uses its
  default, the default wallpaper file is missing (black background).

## VM runbook

```bash
just build && just test && just push && just qcow2
cd ~/Code/Infrastructure/tofu-homelab-cfg/libvirt-srv01
tofu taint 'libvirt_volume.atomic_hyprland_base[0]'   # only to re-upload a new qcow2
tofu plan -out tfplan && tofu apply tfplan
virt-viewer -c qemu+ssh://dwallace@10.10.99.4/system hypr-test
```

Re-uploading the base volume replaces the backing file of hypr-test; destroy and
recreate the VM in the same apply (`tofu taint 'module.vm["hypr-test"].libvirt_domain.this'`)
rather than booting a clone whose backing changed underneath it.

The VM's `~/.config/hypr/local.conf` carries the virtual-monitor and software
rendering settings; it is never managed by the image. First graphical login needs
a password: `ssh dwallace@192.168.70.14 sudo passwd dwallace`.
