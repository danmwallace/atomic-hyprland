# atomic-hyprland

A bootc-built Fedora Hyprland desktop image. See docs/superpowers/specs/ for the design.

## Local loop

```bash
just check-kernel   # base and akmods on the same kernel
just lint-ci        # actionlint + renovate-config-validator via podman
just build          # rootless podman build, tags :44 and :44-<date>-<sha>
just test           # host-side CI helper tests, in-image smoke + dotfile sync tests
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
- Still open from this phase: the role's `10-theme.conf` names an SDDM theme
  that is not installed, so SDDM uses its default. Ollama arrived in Phase 2, signing in Phase 3, the NVIDIA driver in Phase 4.

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
  SELinux module for GPU containers. No 32-bit libraries. Three third-party
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

### Alienware rebase (from Bazzite; not yet run)

The Alienware (10.10.70.27, RTX 2070) runs base Bazzite with NVIDIA drivers,
itself a bootc image, so no reinstall is needed. `/var` and `/home` are kept in
both directions. Do this at the machine, not remotely.

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
   sudo semodule -l | grep nvidia_container
   ```

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

4. Create `~/.config/hypr/local.lua` (never managed by the image):

   ```lua
   hl.env("LIBVA_DRIVER_NAME", "nvidia")
   hl.env("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
   hl.env("NVD_BACKEND", "direct")
   hl.config({ cursor = { no_hardware_cursors = true } })
   ```

   If the integrated and NVIDIA cards fight over ordering (black screen or the
   wrong output), add `hl.env("AQ_DRM_DEVICES", "/dev/dri/cardN")` for the
   NVIDIA card here.

5. In ansible-homelab-cfg: add `alienware` (10.10.70.27) to `hypr_desktops`,
   create `host_vars/alienware/ollama.yml` with `hypr_desktop_ollama_gpu: true`,
   and run `playbooks/fedora-hypr-desktop.yml --limit alienware` (use `--check
   --skip-tags hermes` for the first dry run). Then:

   ```bash
   sudo podman exec ollama nvidia-smi   # the GPU inside the container
   sudo podman logs ollama | grep -i -E "cuda|gpu"
   ```

   If Ollama reports CPU only, check the container's SELinux label first:
   `sudo podman inspect ollama --format '{{.ProcessLabel}}'` should contain
   `nvidia_container_t`.

6. Way back: `sudo bootc rollback && sudo systemctl reboot` returns to
   Bazzite. Restore `/etc/containers/policy.json.bazzite` if you stay there.
