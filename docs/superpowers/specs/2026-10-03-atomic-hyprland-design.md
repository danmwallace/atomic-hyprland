# atomic-hyprland design

Approved 2026-10-03 after brainstorming. Source of truth for the architecture; the
implementation plan lives in docs/superpowers/plans/.

## Context

Dan wants a personal Hyprland desktop rebuilt from source rather than configured
by hand, staying in the Fedora ecosystem to practice for RHEL. Two prior projects
feed into it:

- `danmwallace.fedora.hyprland` (Galaxy, in
  `~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora/`):
  installs Hyprland from the `lionheartp/Hyprland` COPR plus SDDM, Waybar, Wofi,
  nwg-drawer, and renders themed dotfiles (nord, tokyo-night, monochrome). Has
  molecule tests. Reused as-is for packages and dotfiles.
- `ghost-desktop` (archived GitHub repo, Ubuntu): the ideas carried forward are
  the resident AI agent (now `danmwallace.hermes.hermes_native`), the local AI
  toolkit on the GPU (Ollama + LiteLLM), and the dev shell stack. Profiles are
  dropped.

Target: eventually the Alienware (10.10.70.27, RTX 2070), which currently runs
**Bazzite**, itself a Universal Blue bootc image. That means no ISO, kickstart,
or disk wipe is ever needed there: `bootc switch` rebases it in place, keeps
`/home` and `/var`, and `bootc rollback` returns to Bazzite. Not in the control
repo inventory yet. Secure Boot stays off for v1 (Bazzite's state is a useful
reference for how it's currently configured).

Approach chosen: **bootc image** (image mode, same workflow as image mode for
RHEL), based on Universal Blue's `base-main:44` so their prebuilt
`akmods-nvidia-open` RPMs match the kernel. Phasing: **VM on srv01 first**,
Alienware rebase last.

Verified during design (2026-10-03):

| Item | Result |
|---|---|
| `quay.io/fedora/fedora-bootc:44` | exists, 44.20261002.0 |
| `ghcr.io/ublue-os/base-main:44` | exists, kernel label `7.2.8-200.fc44.x86_64` |
| `ghcr.io/ublue-os/akmods-nvidia-open:main-44` | exists, built for `7.2.8-200.fc44` (matches) |
| `ghcr.io/wayblueorg/hyprland-nvidia:latest` | exists; reference for the NVIDIA layer |
| `quay.io/centos-bootc/bootc-image-builder:latest` | exists |
| COPR `lionheartp/Hyprland` | has fedora-44-x86_64 chroot |
| COPR `atim/starship`, `atim/lazygit` | have fedora-44-x86_64 chroots |
| Official F44 repos | have sddm, waybar, nwg-drawer, elvish, fzf, bootc; do NOT have hyprland, hypr*, nwg-dock-hyprland, waypaper, starship, lazygit, nvidia-container-toolkit |
| Local tooling | podman, skopeo present; no libvirt locally; srv01 has libvirt via `tofu-homelab-cfg/libvirt-srv01` |

Security note surfaced during design: the archived `ghost-desktop` repo's
`ALIENWARE.md` contains a LiteLLM master key in plain text. Rotate it if LiteLLM
is still running anywhere. Not part of this plan's edits.

## Architecture (approved)

| Path | Behaviour on bootc | Owner |
|---|---|---|
| `/usr` | immutable, replaced on update | the image |
| `/etc` | image defaults, local edits 3-way merged | image + post-install Ansible (secrets) |
| `/var` incl. `/home` | never touched by updates | runtime data |

```
 ~/Code/atomic-hyprland (new repo)           ansible-homelab-cfg (control repo)
 ┌───────────────────────────────┐           ┌───────────────────────────────┐
 │ Containerfile                 │           │ inventories/lab/.../alienware │
 │ packages, NVIDIA, Quadlets,   │           │ playbooks/fedora-alienware.yml│
 │ dotfiles, /etc defaults       │           │ Hermes, API keys, Ollama      │
 └───────────────┬───────────────┘           │ models, Flatpak list          │
                 │ podman build (CI later)    └───────────────┬───────────────┘
                 ▼                                            │ ssh, after first boot
  ghcr.io/danmwallace/atomic-hyprland:44                      ▼
                 │                                 ┌─────────────────────┐
     ┌───────────┴───────────┐                     │ Alienware, RTX 2070 │
     ▼                       ▼                     │ /usr   image        │
  bootc-image-builder     bootc switch (from       │ /etc   image+Ansible│
  qcow2 → srv01 test VM   Bazzite), then           │ /var   data kept    │
  (phase 1)               bootc upgrade nightly    └─────────────────────┘
                          (phase 4)
```

- **Image is the whole desktop.** Hyprland stack, SDDM, NVIDIA modules, Podman +
  nvidia-container-toolkit, dev shell tools, themed dotfiles (the existing
  Ansible role runs *inside the build*), Quadlets for Ollama and LiteLLM.
- **Ansible does only what an image cannot.** Hermes install (vault keys),
  LiteLLM config with API keys, Ollama model pulls, Flatpak list.
- **Data in `/var`.** Ollama models, `/home/hermes`, Dan's home.

Out of scope for v1: profiles, multi-user, Traefik or any LAN-exposed service,
Khoj, Secure Boot / MOK signing, replacing KDE on the laptop.

## Repository layout: `~/Code/atomic-hyprland` (new git repo, GitHub `danmwallace/atomic-hyprland`)

```
Containerfile
justfile
build/
  playbook.yml              # runs danmwallace.fedora.hyprland with hyprland_home_dir=/etc/skel
  requirements.yml          # danmwallace.fedora >= <new version>, community.general
  packages.txt              # dev shell + hermes_native deps, one per line
  install-nvidia.sh         # copies RPMs from akmods image, installs, nvidia-ctk cdi hook
  check-kernel-match.sh     # compares ostree.linux labels of base and akmods images
  cleanup.sh                # disable COPRs, remove ansible-core, dnf clean, bootc container lint
files/
  usr/share/containers/systemd/ollama.container
  usr/share/containers/systemd/litellm.container
  usr/lib/systemd/system/nvidia-cdi.service        # oneshot: nvidia-ctk cdi generate
  usr/lib/systemd/user/atomic-hyprland-dotfiles.service   # sync skel -> ~/.config on stamp change
  usr/libexec/atomic-hyprland/sync-dotfiles
  usr/share/atomic-hyprland/flatpaks.txt
  etc/sddm.conf.d/10-wayland.conf
  etc/containers/policy.json, registries.d/   # phase 3 (signing)
image-builder/config.toml   # bootc-image-builder user/disk config for the qcow2 (dwallace, SSH key, wheel)
docs/superpowers/specs/2026-10-03-atomic-hyprland-design.md   # this design, committed
README.md
.github/workflows/build.yml  # phase 3
```

## Containerfile shape

```dockerfile
ARG BASE=ghcr.io/ublue-os/base-main:44@sha256:<pinned>
ARG AKMODS=ghcr.io/ublue-os/akmods-nvidia-open:main-44@sha256:<pinned>
ARG NVIDIA=1
ARG THEME=nord

FROM ${AKMODS} AS akmods
FROM ${BASE}
COPY build/ /tmp/build/
COPY files/ /
# 1. dev shell + base packages (COPRs atim/starship, atim/lazygit enabled only for this step)
RUN dnf -y install $(cat /tmp/build/packages.txt) ansible-core
# 2. Hyprland via the existing role, dotfiles into /etc/skel
RUN ansible-galaxy collection install -r /tmp/build/requirements.yml && \
    ansible-playbook -c local -i localhost, /tmp/build/playbook.yml -e hyprland_theme=${THEME}
# 3. NVIDIA (build-arg gated)
COPY --from=akmods /rpms /tmp/akmods-rpms
RUN [ "$NVIDIA" = 1 ] && /tmp/build/install-nvidia.sh || true
# 4. pristine dotfile copy + stamp, enable units, cleanup + lint
RUN cp -a /etc/skel /usr/share/atomic-hyprland/skel && date +%Y%m%d > /usr/share/atomic-hyprland/stamp && \
    systemctl enable sddm nvidia-cdi bootc-fetch-apply-updates.timer && systemctl set-default graphical.target && \
    /tmp/build/cleanup.sh
```

Package list = the existing role's list minus `picom`, `flameshot`, `fish`;
plus dev shell (`elvish starship fzf lazygit ripgrep fd-find bat git gh jq yq
make nodejs npm python3 python3-pip uv skopeo distrobox`) and
`nvidia-container-toolkit` (NVIDIA repo). GUI apps (Firefox, LibreOffice,
Thunderbird, Obsidian, Zed) are Flatpaks via `flatpaks.txt`, not image layers.
Alacritty stays in the image.

NVIDIA install follows wayblue's `hyprland-nvidia` pattern: install
`kmod-nvidia-open` + userspace from `/tmp/akmods-rpms`, set the Hyprland NVIDIA
env (`LIBVA_DRIVER_NAME=nvidia`, `__GLX_VENDOR_LIBRARY_NAME=nvidia`,
`NVD_BACKEND=direct`, `cursor:no_hardware_cursors`) in a drop-in the role's
`hyprland.conf` sources.

## Changes to existing repos

### `danmwallace.fedora.hyprland` (bounded role change, new collection release)

- Add `hyprland_home_dir` default `/home/{{ hyprland_user }}`; every
  `dest: /home/{{ hyprland_user }}/...` uses it. When set to `/etc/skel`, skip
  `owner`/`group`/`become_user` (root-owned, mode 0644/0755).
- Package list cleanup (drop picom, flameshot, fish).
- Make `hyprland.conf.j2` end with `source = ~/.config/hypr/local.conf` (file
  created empty by the role) so per-machine overrides survive syncs.
- Molecule: add a `skel` scenario asserting files land under `/etc/skel/.config`.
- Update `meta/argument_specs.yml`, README, CHANGELOG; release `danmwallace.fedora` 1.1.0.

### `danmwallace.hermes.hermes_native` and `claude_code` (bounded)

- Guard `ansible.builtin.dnf` tasks with
  `when: not (ansible_facts.pkg_mgr == 'atomic_container' or ostree_booted.stat.exists)`
  (stat `/run/ostree-booted` in a pre-task). Molecule check that the guard fires.
- Release `danmwallace.hermes` 1.4.0.

### `ansible-homelab-cfg`

- `inventories/lab/hosts.yml`: new group `hypr_desktops` with `hypr-test` (phase 2)
  and later `alienware` (10.10.70.27, phase 4).
- `inventories/lab/group_vars/hypr_desktops/{services,vault}.yml`: hermes_native,
  claude_code, litellm keys, ollama model list, flatpak list; per-host overrides
  in `host_vars` only where the two differ.
- `playbooks/fedora-hypr-desktop.yml` (hosts: `hypr_desktops`): modelled on `fedora-ai-master.yml` minus
  `podman.common`, `podman.traefik`, `cloudflare_ssl`, `cockpit`, `restic_backup`
  (reassess backup later). Adds a tasks block (or small `danmwallace.fedora.ai_desktop`
  role) that: templates `/etc/litellm/config.yaml`; runs
  `podman exec ollama ollama pull <model>` guarded by `ollama list` output
  (`changed_when` on pull); installs Flatpaks with `community.general.flatpak`.
- `requirements.yml`: bump fedora and hermes collection pins.

### `tofu-homelab-cfg/libvirt-srv01` (phase 1)

- Add a second `libvirt_volume` for the atomic-hyprland qcow2 (uploaded to the
  pool via `virsh vol-upload` or `source` path) and a `hypr-test` VM via the
  existing `modules/libvirt_vm` (`base_volume_id` → new volume). The module's
  cloud-init path is irrelevant to a bootc image; create the user via the
  image-builder `config.toml` instead. The VM needs a virtio-gpu video device
  and either a SPICE/VNC console or `virt-viewer` access to see SDDM; check
  whether the module exposes a graphics block and add one if not.

## Phases

### Phase 1: Image (no NVIDIA) booting Hyprland in a VM on srv01

1. Create the repo, `README.md`, commit the design spec to
   `docs/superpowers/specs/2026-10-03-atomic-hyprland-design.md`. Obsidian:
   `/new-project` "Atomic Hyprland".
2. Role change to `danmwallace.fedora.hyprland` (`hyprland_home_dir`, package
   cleanup, `local.conf` source line), molecule green, release 1.1.0.
3. `Containerfile`, `build/*`, `files/*` (dotfile sync unit, sddm conf).
   `just build` locally (`podman build --build-arg NVIDIA=0`), `just lint`
   (`bootc container lint`), `just check-kernel` (skopeo label compare; runs even
   with NVIDIA=0 so drift is visible early).
4. Push to `ghcr.io/danmwallace/atomic-hyprland:44` from the laptop (`podman push`).
5. `image-builder/config.toml` (user `dwallace`, SSH key, wheel), `just qcow2`
   (bootc-image-builder, **sudo**). Upload the qcow2 to srv01's pool, add the
   volume + `hypr-test` VM in `tofu-homelab-cfg/libvirt-srv01`, `tofu plan`,
   review, `tofu apply`.
6. Verify in the VM: `bootc status` shows the ghcr image; SDDM on the console;
   Hyprland session (software rendering under virtio-gpu, `cursor:no_hardware_cursors`);
   dotfiles present; `elvish` login shell; `ssh dwallace@hypr-test` works.

### Phase 2: Quadlets + post-install Ansible, validated against the VM

1. `ollama.container` (`Image=docker.io/ollama/ollama`,
   `Volume=/var/lib/ollama:/root/.ollama`, `PublishPort=127.0.0.1:11434:11434`;
   GPU attachment lives in a drop-in `ollama.container.d/nvidia.conf` with
   `AddDevice=nvidia.com/gpu=all` and `After=nvidia-cdi.service`, shipped only
   when NVIDIA=1). `litellm.container` (`Image=ghcr.io/berriai/litellm`,
   `Volume=/etc/litellm:/app/config:ro`, `PublishPort=127.0.0.1:4000:4000`).
   Rebuild, push, `bootc upgrade` in the VM: first real exercise of the update path.
2. hermes_native / claude_code ostree guard, release hermes 1.4.0.
3. Control repo: `hypr-test` host in `inventories/lab`, `fedora-hypr-desktop.yml`
   playbook with a `hypr_desktops` group so the Alienware joins later by adding a
   host, not a playbook. Run it. Verify: `curl 127.0.0.1:11434/api/tags` lists
   pulled models (CPU mode), LiteLLM on 4000, Hermes dashboard on 9119, Flatpaks
   installed, second run reports 0 changed.

### Phase 3: CI, signing, updates

1. `.github/workflows/build.yml`: on push to main + nightly; buildah build,
   `bootc container lint`, kernel-match assertion, push tags `44`, `44-YYYYMMDD`,
   `latest`; cosign keyless (OIDC) sign.
2. Ship `/etc/containers/policy.json` + `registries.d/atomic-hyprland.yaml` in
   the image requiring a cosign signature for `ghcr.io/danmwallace/atomic-hyprland`.
3. Confirm `bootc-fetch-apply-updates.timer` stages nightly in the VM; test
   `bootc rollback` once deliberately.
4. Base and akmods digests bumped via Renovate (or a weekly CI job opening a PR).

### Phase 4: NVIDIA layer and the Alienware rebase from Bazzite

1. `build/install-nvidia.sh` + `nvidia-cdi.service` + the Ollama GPU drop-in;
   CI builds with NVIDIA=1 as the default tag (the VM keeps working: the modules
   simply don't load without the hardware, and the Ollama drop-in's device is
   skipped by the `ConditionPathExists=/dev/nvidia0` on `nvidia-cdi.service`).
2. On the Alienware, record the current state for rollback:
   `bootc status`, `rpm-ostree status`, `flatpak list`. Note what Bazzite
   configured in `/etc` (it ships its own NVIDIA setup) so conflicts in the
   3-way `/etc` merge are expected and reviewed.
3. **Confirm with Dan**, then `sudo bootc switch ghcr.io/danmwallace/atomic-hyprland:44`,
   reboot. `/home` and `/var` are preserved. Verify: `nvidia-smi`, SDDM, Hyprland
   session, `bootc status` shows both deployments (rollback target = Bazzite).
4. Add `alienware` to the `hypr_desktops` group, run the playbook. Verify
   `podman logs ollama` shows CUDA detected and models answer on the GPU.
5. README runbook: build, update, rollback, "switch back to Bazzite".

## Failure modes designed for

| Failure | Answer |
|---|---|
| Kernel and akmods drift apart | `check-kernel-match.sh` fails the build; nothing ships |
| COPR drops F44 or breaks Hyprland | build fails, or `bootc rollback` + pin previous date tag |
| Universal Blue changes its base | digest-pinned; a bump is a deliberate PR |
| Ollama starts before CDI spec exists | `After=nvidia-cdi.service` in the NVIDIA drop-in |
| No GPU present (the VM) | `nvidia-cdi.service` has `ConditionPathExists=/dev/nvidia0`; Ollama runs CPU-only |
| Bazzite's `/etc` customisations conflict on rebase | reviewed in phase 4 step 2; `bootc rollback` returns to Bazzite |
| Hermes needs a package not in the image | rebuild, or `distrobox` for one-offs |
| Dotfile update after user exists | stamp-based sync unit at login; `local.conf` never managed |

## Verification (end to end)

- `just build && just lint && just check-kernel` exit 0 locally.
- Phase 1, `hypr-test` VM: `bootc status` shows the ghcr image; SDDM on the
  virtual console; `loginctl` session Type=wayland, Desktop=Hyprland;
  `~/.config/hypr/hyprland.conf` present; `systemctl --user status
  atomic-hyprland-dotfiles` ran once; SSH as dwallace works.
- Phase 2: `bootc upgrade` in the VM picks up the Quadlet rebuild; `curl -s
  127.0.0.1:11434/api/tags` lists models (CPU mode); LiteLLM on 4000; Hermes
  dashboard on 9119; `ansible-playbook fedora-hypr-desktop.yml` second run
  reports 0 changed.
- Phase 3: push a trivial commit, CI builds and signs, `bootc upgrade --check`
  in the VM sees it; an unsigned local tag is refused; `bootc rollback` works.
- Phase 4, Alienware: `bootc status` lists atomic-hyprland booted and Bazzite as
  rollback; `nvidia-smi` lists the RTX 2070; Hyprland session; `podman logs
  ollama` shows CUDA detected; playbook runs clean.

## Sudo / destructive steps that will be confirmed before running

- `bootc-image-builder` (root podman) for the qcow2.
- `tofu apply` against srv01 (phase 1): creates a volume and VM, nothing removed.
- `sudo bootc switch` on the Alienware (phase 4): reversible via `bootc rollback`,
  but it replaces the booted OS, so it gets explicit confirmation.
