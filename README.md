# atomic-hyprland

A bootc-built Fedora Hyprland desktop image. See docs/superpowers/specs/ for the design.

## Local loop

```bash
just check-kernel   # base and akmods on the same kernel
just lint-ci        # actionlint + renovate-config-validator via podman
just build          # rootless podman build, tags :44 and :44-<date>-<sha>
just test           # host tests (theme engine, palettes, bar, includes, pins, CI helpers), in-image smoke + dotfile sync
just qcow2          # sudo; output/qcow2/disk.qcow2 for the srv01 VM
```

Publishing happens only from CI: merge to `main` (or wait for the nightly) to
publish `44`, `44-<date>-<sha>` and `latest`; run the workflow by hand from a
branch (`gh workflow run build.yml --ref <branch>`) to publish a signed
`dev-<branch>` tag you can `bootc switch` a test machine to.

## Phase 1 status (2026-10-03)

- `hypr-test` VM on srv01 (192.168.70.14) boots the image: `bootc status` shows
  `ghcr.io/danmwallace/atomic-hyprland:44`, cloud-init created `dwallace` with
  `/usr/bin/elvish`, the dotfile sync unit ran, SDDM greeter is up on Xorg.
  Verified over SSH 2026-10-03. Graphical login: see the VM runbook.
- Ollama arrived in Phase 2, signing in Phase 3, the NVIDIA driver in Phase 4,
  the look and theme engine (below) on 2026-11-08; the Hyprland config moved
  from the `danmwallace.fedora.hyprland` Ansible role into this repo then.

## Look and themes (2026-11-08)

Design: `docs/superpowers/specs/2026-11-07-look-and-theme-engine-design.md`.
Dark monochrome with one neon accent (`monochrome-green` by default), sharp
geometry (rounding 3, gaps 4/8, solid 2 px accent border, no blur or shadows),
a floating bar that is quiet until something needs attention (glyphs only;
numbers in tooltips; accent for charging / idle-inhibit / do-not-disturb,
red for a hot GPU, low battery, muted audio, no network). The greeter is a
small SDDM theme in the same palette with no virtual keyboard.

**One palette, every app.** A theme is a directory with `colors.toml`,
`backgrounds/` and `icons.theme`. `hypr-theme` renders the templates in
`/usr/share/atomic-hyprland/themed/*.tpl` into
`~/.config/atomic-hyprland/current/theme/`; each app's config carries one
include line pointing there (Hyprland, waybar, mako, wofi, hyprlock, Ghostty,
Alacritty, btop, GTK's `gtk.css`). GTK gets Adwaita-dark + Papirus-Dark through
`gsettings`, Qt goes through Kvantum, Flatpaks follow through the settings
portal plus a per-user `flatpak override`, Chromium's frame colour is fixed at
build from the default palette (Linux Chromium reads only system-wide policy).

```bash
hypr-theme list                 # 17 shipped (below) + yours
hypr-theme set tokyo-night      # renders, swaps, reloads Hyprland, restarts bar/mako/swaybg, pushes gsettings
hypr-theme bg next              # next wallpaper from the theme's backgrounds/ and ~/Pictures/Wallpapers (SUPER+SHIFT+T)
hypr-theme refresh              # re-render after an image update changed a template (login does this for you)
hypr-theme apply                # push gsettings / Flatpak override / Kvantum for the current theme (login does this too)
```

Your own theme: copy a shipped one to `~/.config/atomic-hyprland/themes/<name>/`
and edit `colors.toml`; a directory with the same name as a shipped theme
overlays it. Your own template: `~/.config/atomic-hyprland/themed/<app>.tpl`.
Hooks in `~/.config/atomic-hyprland/hooks/theme-set.d/` run after a switch
with the theme name as `$1`, after the image's own hooks in
`/usr/share/atomic-hyprland/hooks/theme-set.d/`. A user hook with the same
name as an image hook replaces it; an empty, non-executable one disables it.

Shipped themes: `monochrome-green` (default), `monochrome-blue`, `-amber`,
`-magenta`, `-cyan`, `-red`, `-violet`, `-orange` (neon accents on the same
black base), `tokyo-night`, `nord`, `dracula`, `catppuccin-mocha`,
`gruvbox-dark`, `rose-pine`, `kanagawa`, `everforest`, and `neon-night` (an
original: synthwave purple with pink and cyan).

**RGB lighting follows the theme.** Every theme has an `led` colour: the
accent when it is saturated, otherwise a saturated stand-in, because LEDs
wash pale colours out to white. The image's `50-openrgb` hook sets all
OpenRGB devices to it (static) on every switch and at login, using `openrgb`
from `PATH` or an OpenRGB AppImage in `~/AppImages`; on machines with
neither it does nothing. It runs as the transient user unit
`atomic-hyprland-leds` (OpenRGB's device scan takes a few seconds), so check
`journalctl --user -u atomic-hyprland-leds` if the lights don't change. Turn
it off with `: > ~/.config/atomic-hyprland/hooks/theme-set.d/50-openrgb`.
An OpenRGB autostart entry that loads a saved profile at login would
overwrite the colour; remove it.

**Who owns which file in your home.** Three lists under
`/usr/share/atomic-hyprland` decide, and `sync-dotfiles` (login) follows them:

- `managed-files.txt`: overwritten on every image update. Do not edit these;
  the thin `~/.config/hypr/hyprland.lua` is one of them.
- `skel.local`: created once if absent, never written again. Yours:
  `hypr/local.lua`, `waybar/local.jsonc`, `waybar/local.css`, `mako/local`,
  `wofi/local.css`, `ghostty/local`, `alacritty/local.toml`,
  `hypr/hyprlock.local.conf`, `hypr/hypridle.local.conf`. Each is included
  by its image-managed counterpart in the order that makes yours win: waybar
  and Alacritty read the *first* definition, so their skel files are thin
  include lists with yours before the shipped defaults; the others include
  yours last. hyprlock and hypridle blocks add up rather than replace, so a
  different idle timeout means a user template override, not a local file.
- `skel.retired`: paths an earlier image wrote and this one no longer ships
  (the role's `waybar/config`, `hypr/conf/*.lua`, wofi `style-*.css`, nwg
  directories); removed on the next update so they cannot shadow the new files.

The theme is rendered before the compositor starts (`atomic-hyprland-theme@.service`,
a template enabled against uwsm's `wayland-session-pre@.target`); `hyprland.lua`
also carries a built-in fallback palette. Waybar, mako and hypridle run from the
user units their packages ship; the image adds `swaybg.service` and a two-minute
battery warning timer, all bound to `graphical-session.target`.

Session environment (Qt/Kvantum, cursor, `$TERMINAL`, `$BROWSER`) lives in
`/etc/xdg/uwsm/env-hyprland`, so it reaches everything uwsm starts, D-Bus
services such as the keyring prompt included; add your own in
`~/.config/uwsm/env-hyprland`. dconf system defaults make a new home dark
before the first `hypr-theme apply`, and `apply` also runs before the
compositor. The launcher and power menu (wofi) are obsidian glass: a
translucent dark fill over Hyprland blur, which is enabled but only visible
there because every window is opaque. wofi reads its stylesheet as a string,
so `~/.config/wofi/style.css` links to a fully rendered file with absolute
imports; your overrides go in `~/.config/wofi/local.css` as before. AppImages
work (`fuse-libs`).

CI renders every shipped theme and runs the result through
`Hyprland --verify-config` (plus `jq` on the bar's strict-JSON config), so a
Hyprland or template change that breaks the look fails the nightly, not your
login. Fonts: JetBrainsMono Nerd Font (pinned upstream release) and Inter.
Browser: Fedora's `chromium` with the Claude extension force-installed by
managed policy (`/etc/chromium/policies/managed/`); Firefox left with it.

## AI services (Phase 2)

The image ships `ollama.service` (starts on first boot, models under
`/var/lib/ollama`, loopback only). LiteLLM shipped alongside it until
2026-11-07 and was dropped: it was heavy for what it did, and OpenRouter covers
the hosted-model routing it was there for. Claude Code is in the image for
every user. Firefox, LibreOffice and
Thunderbird are Flatpaks installed by the same playbook.

Verified on hypr-test 2026-10-04: Ollama (CPU) with the two small models,
Hermes agent and dashboard active under SELinux enforcing, five Flatpaks,
playbook idempotent. First boot pulls the Ollama image with `ai-images-pull.service`
(podman caps pulls started inside a container unit at five minutes).

## Publishing and trust (Phase 3)

`.github/workflows/build.yml` runs on push to `main`, nightly at 03:00 UTC,
on pull requests (build and test only) and on manual dispatch. It calls the
same `just` recipes as the local loop, then publishes in a fixed order: push
the unique `44-<date>-<sha>` (or `dev-<branch>`) tag via `build/ci-push.sh`,
sign that digest with cosign 3.1.3 in the legacy simple-signing format (the
only one bootc, podman and skopeo verify), and only then re-point `44` and
`latest` at the same digest. No release tag ever names an unsigned image. Runs
on `main` are never cancelled mid-publish. The ghcr package must grant the
repository Write access under "Manage Actions access" for the job token to
push (one-time setting).

The image trusts only signed copies of itself: `/etc/containers/policy.json`
has a `sigstoreSigned` entry for `ghcr.io/danmwallace/atomic-hyprland` keyed
on `/etc/pki/containers/atomic-hyprland.pub` (the repo's `cosign.pub`), and
`registries.d/atomic-hyprland.yaml` makes clients fetch the signature. Other
registries keep the base's catch-all accept-anything rule, which is how the
Ollama image pulls.

Key material: private key in the GitHub secret `COSIGN_PRIVATE_KEY`, backup in
the control repo's `hypr_desktops` vault as `vault_atomic_hyprland_cosign_key`.
Rotation: generate a new pair, commit the new public key next to the old one,
add it to `keyPaths` in `build/30-policy.sh` and a `COPY` in the Containerfile,
let every machine upgrade once, swap the secret, then remove the old key.

Updates: `bootc-fetch-apply-updates.timer` runs `bootc upgrade` (stage only,
via a drop-in) one hour after boot and every eight hours after. The staged
image becomes the default at the next reboot. `bootc status` shows it as
`staged` while it waits. rpm-ostree's automatic timer is disabled.

Renovate (`renovate.json`) opens Monday PRs for the digests in
`build/images.env` (base and akmods grouped, Fedora version bumps disabled),
the pinned action shas, the Claude Code version and the Quadlet image tags.

## NVIDIA (Phase 4)

One image for every machine, always with the NVIDIA driver. It is inert
without the hardware: `hypr-test` has no GPU and runs the same image.

- **Where it comes from.** A first build stage brings in Universal Blue's
  prebuilt `akmods-nvidia-open` image, pinned by digest next to the base in
  `build/images.env`. `build/25-nvidia.sh` bind-mounts its RPMs and runs
  ublue's own `nvidia-install.sh`: kernel module, userspace driver,
  `nvidia-container-toolkit`, `egl-wayland`, `libva-nvidia-driver` and the
  SELinux module for GPU containers (`nvidia_container_t`, which turned out
  not to be needed: with CDI the device nodes inside the container are
  `container_file_t`, which the default `container_t` can open and mmap and
  `nvidia_container_t` can only open, so CUDA fails under it while
  `nvidia-smi` works). No 32-bit libraries. Three third-party
  repos are enabled only for that step (negativo17 `fedora-nvidia`, NVIDIA's
  toolkit repo, the `ublue-os/staging` COPR).
- **Kernel match.** The module is built for one exact kernel. `just
  check-kernel` compares the two images' labels; the build compares the
  module's kernel with the installed `kernel-core` and stops with `kernel
  mismatch: akmods built for X, image has Y`. Either failure means the two
  digests in `build/images.env` must be bumped together.
- **Kernel arguments** (`/usr/lib/bootc/kargs.d/00-nvidia.toml`):
  `rd.driver.blacklist=nouveau modprobe.blacklist=nouveau nvidia-drm.modeset=1`.
  bootc applies them on install, switch and upgrade.
- **No GPU, no failures.** `nvidia-persistenced` and `nvidia-cdi-refresh` carry
  `ConditionPathExists=/proc/driver/nvidia/version`, so they are skipped on
  machines without the card instead of failing.
- **Ollama on the GPU is per host.** The image's `ollama.container` has no GPU
  device, because podman will not start a container whose CDI device is
  missing. Set `hypr_desktop_ollama_gpu: true` for the host in
  ansible-homelab-cfg; the playbook writes
  `/etc/containers/systemd/ollama.container.d/10-nvidia.conf`.
- **Hyprland's NVIDIA environment is per machine** too: it goes in
  `~/.config/hypr/local.lua` (see the Alienware runbook), never in the image.
- `podman build` on its own fails: `AKMODS_IMAGE` has no default. Use
  `just build`, which passes the pinned pair.

## VM runbook

```bash
just qcow2   # pulls the CI-published :44; merge to main first
cd ~/Code/Infrastructure/tofu-homelab-cfg/libvirt-srv01
tofu plan -out tfplan && tofu apply tfplan
virt-viewer -c qemu+ssh://dwallace@10.10.99.4/system hypr-test
```

To re-upload a new qcow2, replace the base volume **and** the VM's root disk and
domain in one apply. Replacing only the base leaves the copy-on-write overlay
"updated in-place" on top of a different backing file (verified with
`tofu plan -replace`), which corrupts the guest:

```bash
tofu plan -out tfplan \
  -replace='libvirt_volume.atomic_hyprland_base[0]' \
  -replace='module.vm["hypr-test"].libvirt_volume.root' \
  -replace='module.vm["hypr-test"].libvirt_domain.this'
tofu apply tfplan
```

Day-to-day updates do not need this: push a new image and run `sudo bootc upgrade`
in the VM instead.

The VM's `~/.config/hypr/local.lua` carries the virtual-monitor and software
rendering settings; it is never managed by the image:

```lua
hl.monitor({ output = "Virtual-1", mode = "preferred", position = "auto", scale = 1 })
hl.config({ cursor = { no_hardware_cursors = true } })
hl.env("WLR_RENDERER_ALLOW_SOFTWARE", "1")
```

First graphical login needs a password: `ssh dwallace@192.168.70.14 sudo passwd dwallace`.

### Phase 3 verification (hypr-test, as root)

1. First signed upgrade: `bootc upgrade && systemctl reboot`. Then `bootc
   status` shows the new version booted; `jq
   '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"]'
   /etc/containers/policy.json` shows `sigstoreSigned`; `systemctl is-enabled
   bootc-fetch-apply-updates.timer rpm-ostreed-automatic.timer` prints
   `enabled` then `disabled`.
2. Positive: `cosign verify --new-bundle-format=false --key
   /etc/pki/containers/atomic-hyprland.pub ghcr.io/danmwallace/atomic-hyprland:44`.
3. Negative, read-only: `skopeo copy
   docker://ghcr.io/danmwallace/atomic-hyprland:44-20261004-7018d1e
   dir:/tmp/unsigned` must fail with a signature error (that tag predates
   signing and is kept for this).
4. Negative, real path: `bootc switch
   ghcr.io/danmwallace/atomic-hyprland:44-20261004-7018d1e` must fail at the
   pull; `bootc status` unchanged. If it ever staged: `bootc switch
   ghcr.io/danmwallace/atomic-hyprland:44`.
5. Rollback: `bootc rollback && systemctl reboot`; the Phase 2 image boots,
   `curl -s 127.0.0.1:11434/api/tags` answers; `bootc rollback && systemctl
   reboot` again returns to the signed image without a download.
6. Timer: `systemctl list-timers bootc-fetch-apply-updates.timer` shows a next
   run. After a newer CI build: `systemctl start
   bootc-fetch-apply-updates.service`, then `bootc status` shows a staged
   deployment and `uptime` shows no reboot.

### Alienware rebase (from Bazzite; done 2026-11-07)

The Alienware is an m15 R3 laptop (172.16.20.14 on Wi-Fi, RTX 2070 Mobile plus
an Intel iGPU with no outputs, LUKS root on btrfs with `home` and `var`
subvolumes). It ran base Bazzite with NVIDIA drivers, itself a bootc image, so
no reinstall was needed. `/var` and `/home` are kept in both directions.
Someone must be at the machine: the LUKS passphrase is typed at every boot.
The steps below are what actually worked; deviations from the plan are noted
inline.

0. Pre-flight on Bazzite, read-only:

   ```bash
   rpm-ostree status          # layered packages or overrides? remove with: rpm-ostree reset
   sudo bootc status          # note the transport: ostree-image-signed or ostree-unverified-registry
   df -h /boot                # our kernel+initramfs set is ~350 MB; two sets must fit
   lspci | grep -Ei "vga|3d"  # is an integrated GPU active as well?
   systemctl is-enabled sshd  # the playbook needs it
   flatpak list
   mokutil --sb-state         # Secure Boot?
   ```

   If `rpm-ostree status` shows `LayeredPackages`, `bootc switch` will refuse
   ("local rpm-ostree modifications"). Either `rpm-ostree reset` and reboot
   first, or do the switch with rpm-ostree in one go (what was done; same
   transport and policy as `bootc switch --enforce-container-sigpolicy`):

   ```bash
   sudo rpm-ostree rebase --uninstall <pkg>... ostree-image-signed:docker://ghcr.io/danmwallace/atomic-hyprland:44
   ```

   Caveat of that path: only bootc reads `/usr/lib/bootc/kargs.d`, so the
   three NVIDIA kargs are missing until the first `bootc upgrade` deploys
   through bootc. Nothing breaks meanwhile (the driver's modprobe.d defaults
   cover both), but check `/proc/cmdline` after that upgrade. Also keep the
   laptop from suspending during the pull: run it under
   `systemd-inhibit --what=sleep:idle` (a KDE idle timeout killed the first
   attempt).

   If Secure Boot is enabled, the NVIDIA module (signed with ublue's akmods
   key) loads only if that key is enrolled: `mokutil --test-key
   /etc/pki/akmods/certs/akmods-ublue.der` must say it is already enrolled
   (it is, if Bazzite's own NVIDIA driver works). Otherwise enrol it first, or
   expect a desktop on software rendering and no `nvidia-smi`, with **no
   failed unit** to point at it: the two NVIDIA services simply skip.

1. Make the first pull verified. Bazzite most likely accepts any image from
   an unlisted registry, so without this the switch pulls ours unchecked. From
   a checkout of this repo, on the Alienware:

   ```bash
   sudo install -m 0644 cosign.pub /etc/pki/containers/atomic-hyprland.pub
   sudo install -m 0644 files/etc/containers/registries.d/atomic-hyprland.yaml /etc/containers/registries.d/
   sudo cp /etc/containers/policy.json /etc/containers/policy.json.bazzite
   sudo jq '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"] = [{"type":"sigstoreSigned","keyPaths":["/etc/pki/containers/atomic-hyprland.pub"],"signedIdentity":{"type":"matchRepository"}}]' \
       /etc/containers/policy.json.bazzite | sudo tee /etc/containers/policy.json >/dev/null
   ```

   No flag loosens a policy refusal; `--enforce-container-sigpolicy` only
   tightens.

2. Switch and reboot. `bootc switch` inherits the current deployment's
   transport, and policy.json is only consulted on the signed transport, so
   force it:

   ```bash
   sudo bootc switch --enforce-container-sigpolicy ghcr.io/danmwallace/atomic-hyprland:44
   sudo systemctl reboot
   ```

   A refusal here ("A signature was required, but no signature exists", or a
   key mismatch) is the policy working: check step 1 before anything else.

3. Verify:

   ```bash
   sudo bootc status                 # ours booted, transport ostree-image-signed, Bazzite as rollback
   nvidia-smi                        # lists the RTX 2070
   systemctl --failed                # empty
   cat /proc/cmdline                 # has our three arguments; Bazzite's own kargs carry over too, duplicates are harmless
   ```

   Expect one failed unit on a Bazzite-born host: `systemd-remount-fs`,
   because Bazzite's `/etc/fstab` (kept, it mounts the `home` and `var`
   subvolumes) has a line for `/` that cannot remount a composefs root
   (`overlay: No changes allowed in reconfigure`). Delete that one line.

   Then log in through SDDM to a Hyprland session.

   Then let the image own the trust files again. ostree keeps any `/etc`
   file that differs from the image, so the three files pre-seeded in step 1
   would otherwise shadow every future image change (a key rotation would
   strand this machine):

   ```bash
   sudo cp /usr/etc/containers/policy.json /etc/containers/policy.json
   sudo cp /usr/etc/pki/containers/atomic-hyprland.pub /etc/pki/containers/
   sudo cp /usr/etc/containers/registries.d/atomic-hyprland.yaml /etc/containers/registries.d/
   sudo ostree admin config-diff | grep -E "policy.json|atomic-hyprland"   # prints nothing
   ```

4. Create `~/.config/hypr/local.lua` (never managed by the image) before the
   first graphical login:

   ```lua
   hl.env("LIBVA_DRIVER_NAME", "nvidia")
   hl.env("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
   hl.env("NVD_BACKEND", "direct")
   hl.config({ cursor = { no_hardware_cursors = true } })
   ```

   Do not set `AQ_DRM_DEVICES` unless Hyprland picks the wrong card: Aquamarine
   skips a card without KMS outputs on its own, and it splits the variable on
   `:`, so a `/dev/dri/by-path/pci-0000:01:00.0-card` value is read as three
   nonexistent devices and the session dies with "Found no gpus to use"
   (crash reports under `~/.cache/hyprland/`). If it is ever needed, use a
   `/dev/dri/cardN` path and accept that the number can change.

5. In ansible-homelab-cfg: add `alienware` (172.16.20.14) to `hypr_desktops`,
   create `host_vars/alienware/ollama.yml` with `hypr_desktop_ollama_gpu: true`,
   and run `playbooks/fedora-hypr-desktop.yml --limit alienware` (use `--check
   --skip-tags hermes` for the first dry run). Then:

   ```bash
   sudo podman exec ollama nvidia-smi   # the GPU inside the container
   sudo podman logs ollama | grep -i -E "cuda|gpu"
   ```

   If Ollama reports CPU only while `nvidia-smi` works inside the container,
   it is the SELinux domain: the drop-in must not set
   `SecurityLabelType=nvidia_container_t` (see the NVIDIA section). Under
   `container_t` the model loads into VRAM; qwen2.5-coder:7b ran at 60 tok/s
   on the RTX 2070 against 9.7 on the CPU.

6. Way back: `sudo bootc rollback && sudo systemctl reboot` returns to
   Bazzite. Restore `/etc/containers/policy.json.bazzite` if you stay there.
