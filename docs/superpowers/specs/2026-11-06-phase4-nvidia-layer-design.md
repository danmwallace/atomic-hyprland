# Phase 4: NVIDIA layer and the Alienware runbook: design

Phase 4 of the atomic-hyprland project (main spec:
`2026-10-03-atomic-hyprland-design.md`). It adds the NVIDIA driver layer to the
image, lets the post-install playbook hand the GPU to Ollama on machines that
have one, and writes the runbook for rebasing the Alienware from Bazzite. It
does **not** perform the rebase.

## Why, and what done looks like

The image exists to run on the Alienware (RTX 2070). Until it carries the
NVIDIA kernel module and userspace, that machine cannot boot it to a desktop
or give Ollama a GPU. Done for this phase: the published `44` image contains a
driver that matches its kernel, still boots and behaves on `hypr-test` (which
has no GPU), and a written, reviewed runbook exists for the Alienware switch.

## Decisions

Dan's, from the main spec (2026-10-03) and 2026-11-06:

- One image for every machine, NVIDIA layer always present. No separate
  `-nvidia` tag.
- Drivers come from Universal Blue's prebuilt `akmods-nvidia-open` image,
  digest-pinned in `build/images.env` next to the base; `check-kernel` already
  fails the build when the two are for different kernels.
- The Alienware is reached with `bootc switch` from Bazzite and always with
  Dan's explicit confirmation. It is powered off and Dan is away, so the switch
  is out of scope for this phase.
- Dan asked to proceed without a question round. Everything below marked
  **(my call)** was decided by the builder and is his to overrule.

Builder's calls:

- **Use ublue's installer, not our own (my call).** The pinned akmods image
  ships `rpms/ublue-os/nvidia-install.sh`. It installs the kmod, the userspace
  driver, `nvidia-container-toolkit`, `egl-wayland`, `libva-nvidia-driver`,
  the SELinux module for containers, enables `nvidia-cdi-refresh` and
  `nvidia-persistenced`, and verifies kmod and driver versions agree. Calling
  it tracks upstream; the main spec's `install-nvidia.sh` and custom
  `nvidia-cdi.service` are superseded.
- **No 32-bit libraries (my call).** `MULTILIB=0`. They exist for Steam and
  Wine, which this image does not ship.
- **The `NVIDIA` build argument is removed (my call).** A flag that builds an
  image failing its own smoke tests is a trap. `just build` loses its second
  parameter.
- **GPU for Ollama is switched on per host by the playbook, not in the image
  (my call).** `AddDevice=nvidia.com/gpu=all` makes podman refuse to start the
  container when no CDI spec exists, which would break Ollama on `hypr-test`
  and any GPU-less machine. Verified: a drop-in at
  `/etc/containers/systemd/ollama.container.d/10-nvidia.conf` merges with the
  unit in `/usr/share/containers/systemd`. This replaces the main spec's
  image-shipped drop-in.
- **Hyprland's NVIDIA environment lives in the machine's `local.lua` (my
  call).** `__GLX_VENDOR_LIBRARY_NAME=nvidia` set image-wide would break GL on
  the VM. `local.lua` is already the per-machine override and is never managed
  by the image. No role change, no collection release.

## Facts verified 2026-11-06

| Item | Result |
|---|---|
| Pinned pair | base `sha256:69c8d37d…`, akmods `sha256:6e3cb82b…`; `check-kernel: ok 7.2.8-200.fc44.x86_64` |
| akmods image | no shell (scratch). Contains `rpms/kmods/kmod-nvidia-7.2.8-200.fc44.x86_64-615.71.09-2.fc44.x86_64.rpm`, `rpms/kmods/nvidia-vars`, `rpms/nvidia/*.rpm` (driver 615.71.09, x86_64 + i686 + noarch), `rpms/ublue-os/nvidia-install.sh`, `rpms/ublue-os/ublue-os-nvidia-addons-0.15-2.fc44.noarch.rpm`, and `kernel-rpms/` (unused here: the base already has that kernel) |
| `nvidia-vars` | `KERNEL_VERSION=7.2.8-200.fc44.x86_64`, `NVIDIA_AKMOD_VERSION=615.71.09-2`, `KMOD_REPO=nvidia` |
| `nvidia-install.sh` inputs | `AKMODNV_PATH` (default `/tmp/akmods-rpms`), `MULTILIB` (default 1), `IMAGE_NAME` (must be set; `set -u`). Requires dnf5. Enables then disables the `fedora-nvidia*`, `nvidia-container-toolkit` and `ublue-os/staging` repos. Edits `/usr/lib/dracut/dracut.conf.d/99-nvidia.conf` to force-load `i915 amdgpu nvidia` |
| `ublue-os-nvidia-addons` | repo files, `70-nvidia-cdi-refresh.preset`, `nvidia-cdi-refresh.service.d/10-ublue-ordering.conf`, `nvidia-container.pp` |
| How ublue calls it | `ublue-os/main` Containerfile: `--mount=type=bind,from=akmods_nvidia,src=/rpms,dst=/tmp/akmods-nv-rpms`, then the script, then `initramfs.sh`. Aurora: `IMAGE_NAME=… MULTILIB=0 …/nvidia-install.sh`, removes `/usr/share/vulkan/icd.d/nouveau_icd.*.json`, links `libnvidia-ml.so`, writes `/usr/lib/bootc/kargs.d/00-nvidia.toml` |
| ublue `initramfs.sh` | `DRACUT_NO_XATTR=1 dracut --no-hostonly --kver "$KVER" --reproducible -v --add ostree -f /lib/modules/$KVER/initramfs.img; chmod 0600` |
| Our image today | one kernel dir `/usr/lib/modules/7.2.8-200.fc44.x86_64` with `initramfs.img`; `dracut`, `lsinitrd`, `semodule` present |
| Quadlet drop-in | `/etc/containers/systemd/ollama.container.d/10-nvidia.conf` with `AddDevice=nvidia.com/gpu=all` yields `--device nvidia.com/gpu=all` in the generated `ollama.service` (generator dry-run in the image) |
| Alienware | off; base Bazzite with NVIDIA drivers (Dan, 2026-11-06); not in the inventory |
| hypr-test | build `20261106-45ce3f2`, 12 GB free of 39 GB |

## Image

### Containerfile

- `ARG AKMODS_IMAGE` declared before the first `FROM`; a second stage
  `FROM ${AKMODS_IMAGE} AS akmods`.
- A new step between the role and `COPY files/ /`, so editing static files
  does not re-run it:
  `RUN --mount=type=bind,from=akmods,src=/rpms,dst=/tmp/akmods-rpms /tmp/build/25-nvidia.sh`
  The bind mount keeps a gigabyte of RPMs out of the image layers.
- The `ARG NVIDIA` line and its guard `RUN` are removed.

### `build/25-nvidia.sh`

1. Fail early with a clear message if `KERNEL_VERSION` from `nvidia-vars`
   differs from `rpm -q kernel-core` in the image. `check-kernel` compares
   image labels before the build; this compares what is actually installed.
2. `IMAGE_NAME=base AKMODNV_PATH=/tmp/akmods-rpms MULTILIB=0 /tmp/akmods-rpms/ublue-os/nvidia-install.sh`
3. As Aurora does: remove `/usr/share/vulkan/icd.d/nouveau_icd.*.json`;
   `ln -sf libnvidia-ml.so.1 /usr/lib64/libnvidia-ml.so`.
4. Regenerate the initramfs exactly as ublue's `initramfs.sh` does, because
   the installer changed the dracut config.

### `files/usr/lib/bootc/kargs.d/00-nvidia.toml`

```toml
kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]
```

Aurora's fourth argument, `initcall_blacklist=simpledrm_platform_driver_init`,
is left out **(my call)**: this image also boots on machines without NVIDIA,
where simpledrm is the only early console. If the Alienware shows the known
two-card ordering problem, it is added then.

### Machines without an NVIDIA GPU

Requirement: on `hypr-test` this layer leaves no unit in the `failed` state
and the desktop, Ollama, LiteLLM and Hermes behave as before. Where a unit the
installer enabled fails without hardware, the image ships a drop-in for it
with `ConditionPathExists=/proc/driver/nvidia/version`. Which units need one
is determined by booting the build on `hypr-test` before merge is considered
final; candidates are `nvidia-persistenced.service` and
`nvidia-cdi-refresh.service`.

### justfile

`build` passes `--build-arg AKMODS_IMAGE="$AKMODS_IMAGE"` from
`build/images.env` and loses the `nvidia` parameter. README's local-loop block
and "Known gaps" line are updated.

## Ollama on the GPU (control repo)

`ansible-homelab-cfg`, `playbooks/tasks/hypr-desktop/ollama.yml`:

- New variable `hypr_desktop_ollama_gpu` (default `false`, set in
  `group_vars/hypr_desktops/ollama.yml`).
- When true: ensure `/etc/containers/systemd/ollama.container.d/10-nvidia.conf`
  exists with

  ```ini
  # Managed by Ansible. Hands every NVIDIA GPU to Ollama through CDI.
  [Unit]
  After=nvidia-cdi-refresh.service
  Wants=nvidia-cdi-refresh.service

  [Container]
  AddDevice=nvidia.com/gpu=all
  ```

  then daemon-reload and restart `ollama.service`.
- When false: ensure the file is absent (same handler), so turning it off
  works.
- The Alienware gets `hypr_desktop_ollama_gpu: true` in its `host_vars` when
  it joins the inventory. It is not added now: an unreachable host would fail
  every playbook run.

## Testing

### `tests/image-smoke.sh` additions

- `rpm -q kmod-nvidia nvidia-driver nvidia-driver-cuda nvidia-container-toolkit egl-wayland libva-nvidia-driver ublue-os-nvidia-addons`
- kmod and driver versions are equal.
- Exactly one kernel directory under `/usr/lib/modules`, and a `nvidia.ko*`
  file exists under it.
- The kernel the kmod was built for equals the installed `kernel-core`.
- No 32-bit NVIDIA packages (`! rpm -qa | grep -E 'nvidia.*\.i686'`).
- The initramfs contains the nvidia module (`lsinitrd … | grep nvidia.ko`).
- `/usr/lib/bootc/kargs.d/00-nvidia.toml` exists, parses as TOML (python
  `tomllib`), and lists the three arguments.
- `nvidia-ctk --version` runs.
- `nvidia-cdi-refresh.path` and `nvidia-persistenced.service` are enabled.
- The NVIDIA repos and every COPR are disabled after the build (the existing
  COPR check already covers `ublue-os/staging`; add `dnf repolist --enabled`
  does not list `nvidia`).
- `/usr/share/vulkan/icd.d/nouveau_icd.*.json` is absent.
- The shipped `ollama.container` still has **no** `AddDevice` line (GPU is
  per host).

### Host-side

- `tests/test-justfile.sh`: `build` has no `nvidia` parameter and passes
  `AKMODS_IMAGE`.

### On hypr-test (no GPU)

Reached with a signed `dev-dw-phase4` tag from a manual workflow dispatch, so
`44` is not touched until this passes:

1. `bootc switch` to the dev tag, reboot. It boots, SDDM is active, the user's
   Hyprland config still verifies.
2. `systemctl --failed` lists nothing.
3. `/proc/cmdline` carries the three arguments; `lsmod` shows no `nvidia`.
4. `curl 127.0.0.1:11434/api/tags` answers; LiteLLM and Hermes are active.
5. The playbook runs with `hypr_desktop_ollama_gpu` false: no drop-in,
   `changed=0`.

After merge and publish: `bootc switch` back to `:44`, reboot, same checks.

### Not testable in this phase

Anything that needs the GPU: module load, `nvidia-smi`, a Hyprland session on
NVIDIA, Ollama on CUDA, the CDI spec. These are the Alienware runbook's
verification steps.

## Alienware runbook (written to README, not executed)

1. Record the current state: `bootc status`, `rpm-ostree status`,
   `flatpak list`, a copy of `/etc` customisations of note.
2. Dan confirms. `sudo bootc switch ghcr.io/danmwallace/atomic-hyprland:44`.
   Bazzite's policy must accept our image: if the pull is refused for want of
   a policy entry, the README gives the one-off `--enforce-container-sigpolicy`
   free form and the reason.
3. Reboot. Verify: `bootc status` (ours booted, Bazzite as rollback),
   `nvidia-smi`, SDDM, a Hyprland session.
4. Create `~/.config/hypr/local.lua` with the NVIDIA environment
   (`LIBVA_DRIVER_NAME=nvidia`, `__GLX_VENDOR_LIBRARY_NAME=nvidia`,
   `NVD_BACKEND=direct`, `cursor.no_hardware_cursors`).
5. Add `alienware` (10.10.70.27) to `hypr_desktops` with
   `hypr_desktop_ollama_gpu: true`; run the playbook (`--skip-tags hermes` on
   the first check run). Verify `podman logs ollama` reports CUDA.
6. Way back: `sudo bootc rollback` returns to Bazzite; `/var` and `/home` are
   kept in both directions.

## Rollback

- A build that fails the kernel or version assertions publishes nothing.
- `hypr-test` is tested on a `dev-` tag first; `bootc switch` back to `:44`
  undoes it. After publish, `bootc rollback` returns to `20261106-45ce3f2`.

## Out of scope

Running the Alienware switch; Secure Boot and module signing; 32-bit
libraries, Steam, gamescope; a role or collection change; an image-wide
Hyprland NVIDIA config; bumping the pinned base and akmods digests (Renovate's
job, still not installed).
