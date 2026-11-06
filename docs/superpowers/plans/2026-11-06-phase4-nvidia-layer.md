# Phase 4: NVIDIA Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a kernel-matched NVIDIA driver layer in the one published image without changing how it behaves on a machine with no GPU, let the playbook give Ollama the GPU per host, and write the Alienware runbook.

**Architecture:** A first build stage brings in the pinned ublue akmods image; one new build step bind-mounts its RPMs and runs ublue's own `nvidia-install.sh`, then restores repo state and regenerates the initramfs. Static files add kernel arguments and hardware conditions on the two NVIDIA services. The control repo gains a default-off Quadlet drop-in for Ollama. A signed `dev-dw-phase4` tag is proven on hypr-test, with screenshots, before `44` moves.

**Tech Stack:** podman/buildah multi-stage build with `RUN --mount=type=bind`, dnf5, dracut, bootc `kargs.d`, systemd drop-ins, Podman Quadlet, Ansible, libvirt `virsh screenshot`.

**Spec:** `docs/superpowers/specs/2026-11-06-phase4-nvidia-layer-design.md`

## Global Constraints

- Branch `dw/phase4`; Conventional Commits; commit trailers as in the session's attribution block.
- One image, NVIDIA always present. No `NVIDIA` build argument, no `-nvidia` tag.
- Installer call, verbatim: `IMAGE_NAME=base AKMODNV_PATH=/tmp/akmods-rpms MULTILIB=0 /tmp/akmods-rpms/ublue-os/nvidia-install.sh`.
- Mount, verbatim: `RUN --mount=type=bind,from=akmods,src=/rpms,dst=/tmp/akmods-rpms /tmp/build/25-nvidia.sh`. The akmods `FROM` is first; `FROM ${BASE_IMAGE}` is the last `FROM`.
- Kernel arguments, exactly: `rd.driver.blacklist=nouveau`, `modprobe.blacklist=nouveau`, `nvidia-drm.modeset=1`. No simpledrm argument.
- Hardware condition, exactly: `ConditionPathExists=/proc/driver/nvidia/version` (no `|`), for `nvidia-persistenced.service` and `nvidia-cdi-refresh.service`.
- The image's `ollama.container` keeps no `AddDevice`. GPU is per host: `/etc/containers/systemd/ollama.container.d/10-nvidia.conf`, variable `hypr_desktop_ollama_gpu` (default `false`).
- After the build: no enabled COPR repo file, nothing matching `nvidia` in `dnf repolist --enabled`, `fedora-cisco-openh264` in the state the base shipped.
- Shell: 4-space indent, `set -euo pipefail`. YAML/TOML/INI: 2-space where nested. LF, trailing newline.
- `44` is not re-pointed until the hypr-test gate (Task 5) passes on the dev tag. If the gate fails: VM back to `:44`, PR left open, report.
- The Alienware is never touched in this plan.
- Control repo work happens in a git worktree off `origin/main`; its main checkout is on Dan's `dw/srv01-nm-bridge` branch and is not switched.

## Review Focus

1. **Base and akmods for different kernels** (a Renovate PR that bumps only one digest and somehow passes the label check). Expected: the build stops with a message naming both kernels before any package is installed. Pinned by Task 1's mismatch test.
2. **A machine with no NVIDIA GPU.** Expected: no failed unit, desktop draws, Ollama on CPU. Pinned by Task 2's drop-in checks and Task 5's gate.
3. **A third-party repo is down during the build.** Expected: the build fails; nothing is published. No test; the reviewer checks `25-nvidia.sh` has no `|| true` and keeps `pipefail`.
4. **GPU switched on, then off again, by the playbook.** Expected: the drop-in is removed and Ollama restarted without it. Pinned by Task 4's check-mode runs for both values.
5. **`podman build` without `AKMODS_IMAGE`** (someone bypasses `just`). Expected: an immediate, readable failure rather than an image built on the wrong stage. Pinned by Task 1's justfile test that `just build` always passes it; the bare failure mode is documented in the README.

---

### Task 1: The driver layer

**Files:**
- Create: `build/25-nvidia.sh`, `tests/test-nvidia-build.sh`
- Modify: `Containerfile`, `justfile`, `tests/image-smoke.sh`, `tests/test-justfile.sh`

**Interfaces:**
- Produces: `build/25-nvidia.sh` (no arguments; reads `AKMODNV_PATH`, default `/tmp/akmods-rpms`); `just build theme="nord"` passing `BASE_IMAGE` and `AKMODS_IMAGE`.

- [ ] **Step 1: Write the failing host-side tests**

`tests/test-nvidia-build.sh` (same `check` helper as the other host tests), run from the repo root against the **current** local image:

```bash
img=ghcr.io/danmwallace/atomic-hyprland:44
fake="$(mktemp -d)"; trap 'rm -rf "$fake"' EXIT
mkdir -p "$fake/kmods" "$fake/ublue-os"
printf 'KERNEL_VERSION=0.0.0-1.fc44.x86_64\nNVIDIA_AKMOD_VERSION=1-1\n' > "$fake/kmods/nvidia-vars"
printf '#!/bin/bash\necho INSTALLER-RAN\n' > "$fake/ublue-os/nvidia-install.sh"; chmod +x "$fake/ublue-os/nvidia-install.sh"
run() { podman run --rm -v ./build:/b:ro,Z -v "$fake":/tmp/akmods-rpms:ro,Z "$img" bash /b/25-nvidia.sh 2>&1; }
export -f run; export img fake
# A kmod built for another kernel must stop the build before the installer runs.
check bash -c '! run >/dev/null'
check bash -c 'run | grep -q "kernel mismatch: akmods built for 0.0.0-1.fc44.x86_64, image has "'
check bash -c '! run | grep -q INSTALLER-RAN'
```

Add to `tests/test-justfile.sh`:

```bash
check bash -c 'just -n build 2>&1 | grep -q -- "--build-arg AKMODS_IMAGE="'
check bash -c '! just -n build 2>&1 | grep -q "NVIDIA="'
check bash -c '! just --show build | head -3 | grep -q nvidia='
```

Wire `bash tests/test-nvidia-build.sh` into `just test` after `test-build-pins.sh`.

- [ ] **Step 2: Run them; expect failure**

Run: `bash tests/test-nvidia-build.sh; bash tests/test-justfile.sh | grep -E "AKMODS|NVIDIA|nvidia="`
Expected: all three mismatch checks FAIL (no such script: the first passes vacuously, the message checks fail); the three justfile checks FAIL.

- [ ] **Step 3: Write `build/25-nvidia.sh`**

```bash
#!/usr/bin/bash
# NVIDIA driver layer. The RPMs and ublue's installer come from the pinned
# akmods image, bind-mounted at AKMODNV_PATH by the Containerfile.
set -euo pipefail
: "${AKMODNV_PATH:=/tmp/akmods-rpms}"

# check-kernel compares image labels before the build; this compares what is
# installed. A kmod for another kernel would install and then never load.
source "${AKMODNV_PATH}/kmods/nvidia-vars"
image_kernel="$(rpm -q --queryformat='%{evr}.%{arch}' kernel-core)"
if [ "${KERNEL_VERSION}" != "${image_kernel}" ]; then
    echo "kernel mismatch: akmods built for ${KERNEL_VERSION}, image has ${image_kernel}" >&2
    exit 1
fi

# The installer disables this repo and never restores it.
openh264_was_enabled=0
dnf5 repolist --enabled | grep -q '^fedora-cisco-openh264' && openh264_was_enabled=1

IMAGE_NAME=base AKMODNV_PATH="${AKMODNV_PATH}" MULTILIB=0 "${AKMODNV_PATH}/ublue-os/nvidia-install.sh"

# It enables ublue-os/staging with `copr enable` but only overrides it off,
# leaving the repo file enabled=1.
dnf -y copr disable ublue-os/staging
[ "${openh264_was_enabled}" = 1 ] && dnf5 config-manager setopt fedora-cisco-openh264.enabled=1

# As Aurora does: no nouveau Vulkan ICD next to the NVIDIA one, and the
# unversioned libnvidia-ml name some tools dlopen.
rm -f /usr/share/vulkan/icd.d/nouveau_icd.*.json
ln -sf libnvidia-ml.so.1 /usr/lib64/libnvidia-ml.so

# The installer rewrote the dracut config to force-load the driver; rebuild
# the initramfs the way ublue's initramfs.sh does.
export DRACUT_NO_XATTR=1
dracut --no-hostonly --kver "${image_kernel}" --reproducible -v --add ostree \
    -f "/usr/lib/modules/${image_kernel}/initramfs.img"
chmod 0600 "/usr/lib/modules/${image_kernel}/initramfs.img"
```

- [ ] **Step 4: Containerfile and justfile**

Containerfile: `ARG AKMODS_IMAGE` beside `ARG BASE_IMAGE` at the top; `FROM ${AKMODS_IMAGE} AS akmods` as the first `FROM`; delete `ARG NVIDIA=0` and the guard `RUN`; insert the mount `RUN` from Global Constraints after the role step and before `COPY files/ /`, with a one-line comment that the bind mount keeps the RPMs out of the layers.

justfile `build`: signature `build theme="nord"`; add `--build-arg AKMODS_IMAGE="$AKMODS_IMAGE"`; remove the `NVIDIA` build-arg.

- [ ] **Step 5: Host tests pass**

Run: `bash tests/test-nvidia-build.sh && bash tests/test-justfile.sh`
Expected: all `ok`.

- [ ] **Step 6: Add the in-image smoke checks (failing until the build)**

In `tests/image-smoke.sh`, a block headed `# Phase 4: NVIDIA layer (present on every machine; inert without the hardware)`:

```bash
check rpm -q kmod-nvidia nvidia-driver nvidia-driver-cuda nvidia-container-toolkit egl-wayland libva-nvidia-driver ublue-os-nvidia-addons
check test "$(rpm -q --qf '%{VERSION}' kmod-nvidia)" = "$(rpm -q --qf '%{VERSION}' nvidia-driver)"
kver="$(rpm -q --qf '%{evr}.%{arch}' kernel-core)"
check test "$(ls /usr/lib/modules | wc -l)" = 1
check bash -c "find /usr/lib/modules/${kver} -name 'nvidia.ko*' | grep -q ."
check bash -c "rpm -q kmod-nvidia --qf '%{NAME}-%{VERSION}' >/dev/null && rpm -ql kmod-nvidia | grep -q \"/${kver}/\""
check bash -c '! rpm -qa | grep -E "nvidia.*\.i686"'
check bash -c "lsinitrd /usr/lib/modules/${kver}/initramfs.img | grep -q 'nvidia.ko'"
check bash -c 'nvidia-ctk --version | grep -qi "version"'
check test "$(systemctl is-enabled nvidia-cdi-refresh.path 2>/dev/null)" = enabled
check test "$(systemctl is-enabled nvidia-persistenced.service 2>/dev/null)" = enabled
check bash -c '! dnf5 repolist --enabled 2>/dev/null | grep -qi nvidia'
check bash -c '! ls /usr/share/vulkan/icd.d/nouveau_icd.*.json 2>/dev/null | grep -q .'
```

The existing COPR-file check is unchanged; it now also guards `ublue-os/staging`.

- [ ] **Step 7: Build and test**

Run: `just build > <log> 2>&1; echo rc=$?` then `just test`
Expected: build `rc=0`; the log contains ublue's `nvidia-install.sh` trace and a dracut run; suite all `ok`, exit 0. If the installer or dracut fails, read the log and use superpowers:systematic-debugging; do not add `|| true`.

- [ ] **Step 8: Commit**

`git commit -m "feat(image): add the NVIDIA driver layer from ublue akmods"` with a body listing the new third-party repos used at build time (negativo17 fedora-nvidia, NVIDIA container toolkit, ublue-os/staging COPR).

---

### Task 2: Kernel arguments and GPU-less behaviour

**Files:**
- Create: `files/usr/lib/bootc/kargs.d/00-nvidia.toml`, `files/usr/lib/systemd/system/nvidia-persistenced.service.d/10-require-gpu.conf`, `files/usr/lib/systemd/system/nvidia-cdi-refresh.service.d/10-require-gpu.conf`
- Modify: `tests/image-smoke.sh`

- [ ] **Step 1: Failing smoke checks**

```bash
kargs=/usr/lib/bootc/kargs.d/00-nvidia.toml
check test -f "$kargs"
check python3 -c "import tomllib,sys; k=tomllib.load(open('$kargs','rb'))['kargs']; sys.exit(0 if k==['rd.driver.blacklist=nouveau','modprobe.blacklist=nouveau','nvidia-drm.modeset=1'] else 1)"
for u in nvidia-persistenced nvidia-cdi-refresh; do
    d="/usr/lib/systemd/system/${u}.service.d/10-require-gpu.conf"
    check test -f "$d"
    check grep -qx 'ConditionPathExists=/proc/driver/nvidia/version' "$d"
    check bash -c "systemctl cat ${u}.service | grep -q 10-require-gpu.conf"
done
# GPU for Ollama is switched on per host by the playbook, never in the image.
check bash -c '! grep -rq "AddDevice" /usr/share/containers/systemd/'
```

- [ ] **Step 2:** Run `just test`; expect the kargs and drop-in checks to FAIL, the `AddDevice` check to pass.
- [ ] **Step 3:** Write the three files with the exact content from the spec (the TOML line; the drop-in with its two-line comment and `[Unit]` section).
- [ ] **Step 4:** `just build && just test`; expect all `ok`. `bootc container lint` (inside the build) must accept the kargs file.
- [ ] **Step 5:** Commit `feat(image): nouveau kernel arguments and GPU conditions on NVIDIA units`.

---

### Task 3: README and workflow comment

**Files:** Modify `README.md`, `.github/workflows/build.yml` (comment only)

- [ ] **Step 1:** Failing doc check: `grep -q "^## NVIDIA" README.md && grep -q "^### Alienware rebase" README.md && ! grep -q "no NVIDIA" README.md && ! grep -q "20 GB free" .github/workflows/build.yml` exits non-zero.
- [ ] **Step 2:** README: local-loop block shows `just build` with no flag; the Phase 1 "Known gaps" line loses "no NVIDIA" and the unsigned-image clause (both are no longer true). New `## NVIDIA` section: where the driver comes from, the kernel-match rule and what to do when `check-kernel` or the build's own assertion fails, the three kernel arguments, why the two services are conditional, that GPU for Ollama is the playbook variable, and that `podman build` needs `AKMODS_IMAGE` (use `just build`). New `### Alienware rebase` under the VM runbook: steps 0 to 6 from the spec, with the `local.lua` block written out in Lua and the three files to pre-seed on Bazzite named with their paths. Workflow: replace the stale "~20 GB free" comment with the measured figures (145 GB disk, about 107 GB free after cleanup; image about 10 GB).
- [ ] **Step 3:** Re-run the check (exit 0) and `just lint-ci` (exit 0).
- [ ] **Step 4:** Commit `docs: NVIDIA layer and the Alienware rebase runbook`.

---

### Task 4: Ollama GPU drop-in in the control repo

**Files (in a worktree of `ansible-homelab-cfg` off `origin/main`, branch `dw/hypr-ollama-gpu`):**
- Modify: `playbooks/tasks/hypr-desktop/ollama.yml`, `playbooks/fedora-hypr-desktop.yml` (handler), `inventories/lab/group_vars/hypr_desktops/ollama.yml`
- Create: `playbooks/templates/hypr-desktop/ollama-nvidia.conf.j2`

**Interfaces:** variable `hypr_desktop_ollama_gpu` (bool, default `false`); handler `Restart ollama`.

- [ ] **Step 1:** Failing check: `ansible-playbook playbooks/fedora-hypr-desktop.yml --limit hypr-test --check --diff --skip-tags hermes -e hypr_desktop_ollama_gpu=true | grep -q "10-nvidia.conf"` exits non-zero (no such task yet).
- [ ] **Step 2:** Tasks, FQCN, names describing state: "Ensure the Ollama Quadlet drop-in directory exists" (`ansible.builtin.file`, only when the variable is true); "Ensure Ollama has the NVIDIA GPU through CDI" (`ansible.builtin.template` to `/etc/containers/systemd/ollama.container.d/10-nvidia.conf`, mode `0644`, `when: hypr_desktop_ollama_gpu | bool`, notify `Restart ollama`); "Ensure Ollama has no GPU drop-in" (`ansible.builtin.file state=absent`, `when: not (hypr_desktop_ollama_gpu | bool)`, notify `Restart ollama`). Place them before the existing "Ensure Ollama is running" task. Handler `Restart ollama`: `ansible.builtin.systemd_service` with `daemon_reload: true`, `state: restarted`, `name: ollama.service`. Template content exactly as in the spec. Default `hypr_desktop_ollama_gpu: false` in the group vars with a one-line comment.
- [ ] **Step 3:** Verify both directions in check mode against hypr-test: with `-e hypr_desktop_ollama_gpu=true` the diff shows the file with `AddDevice=nvidia.com/gpu=all` and `SecurityLabelType=nvidia_container_t`; with the default, the three new tasks report `ok`/`skipped` and the play ends `changed=0`. Then a real run with the default: `changed=0`. `ansible-lint` on the changed files and the repo's own lint target are clean.
- [ ] **Step 4:** Commit `feat(hypr-desktop): optional NVIDIA GPU for Ollama via Quadlet drop-in`, push, open a PR, wait for its lint check, merge. Remove the worktree.

---

### Task 5: The hypr-test gate on a signed dev tag

**Files:** none in the repo (a ledger note records the evidence).

- [ ] **Step 1:** Push `dw/phase4`, open the PR against `main` (build-only CI). Expected: green; the `df -h /` line still shows ample space.
- [ ] **Step 2:** `gh workflow run build.yml --ref dw/phase4`; watch to green. Expected: `Push version tag` and `Sign` run for `dev-dw-phase4`; `Push release tags` is skipped; `skopeo inspect …:44` still reports version `20261106-45ce3f2`.
- [ ] **Step 3:** On hypr-test: `df -h /boot /sysroot`; `sudo bootc switch ghcr.io/danmwallace/atomic-hyprland:dev-dw-phase4`; reboot. Expected: it comes back on SSH; `bootc status` shows the dev image booted.
- [ ] **Step 4:** Checks 2, 3 and 5 from the spec: `systemctl --failed --no-legend` prints nothing; `systemctl status nvidia-persistenced nvidia-cdi-refresh` each show the unmet condition; `/proc/cmdline` has the three arguments; `lsmod | grep -c '^nvidia'` is 0; Ollama answers; `litellm`, `hermes-agent`, `hermes-dashboard` active.
- [ ] **Step 5:** Check 4, rendering. Capture the greeter: `virsh -c qemu+ssh://dwallace@10.10.99.4/system screenshot hypr-test <file>.ppm`, convert to PNG, look at it. Then write `/etc/sddm.conf.d/99-autologin-test.conf` (`[Autologin]`, `User=dwallace`, `Session=hyprland`), restart `sddm`, wait, capture again, look at it, then **remove the file and restart `sddm`** whatever the outcome. Expected: the first image shows the SDDM greeter, the second a Hyprland session with Waybar and the wallpaper; `journalctl -b -u sddm` and the Xorg log have no fatal error.
- [ ] **Step 6:** Check 6: the Task 4 playbook run on this build ends `changed=0`.
- [ ] **Step 7:** Record pass/fail per check in the ledger. Any failure in Steps 3 to 5: `sudo bootc switch ghcr.io/danmwallace/atomic-hyprland:44`, reboot, stop the plan, report.

---

## After the plan

Fresh whole-branch review, one fix pass, then: merge the PR, watch the publish run, `bootc switch` hypr-test back to `:44`, reboot, repeat Task 5 Steps 4 and 5, update the Obsidian project and memory. The Alienware runbook is handed to Dan unexecuted.
