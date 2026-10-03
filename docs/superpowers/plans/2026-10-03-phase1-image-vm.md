# atomic-hyprland Phase 1 Implementation Plan: image boots Hyprland in a VM on srv01

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a bootc container image that boots to an SDDM login and a working Hyprland session, prove it in a `hypr-test` libvirt VM on srv01, and leave a repeatable build/push/qcow2 loop behind.

**Architecture:** One Containerfile on top of `ghcr.io/ublue-os/base-main:44` installs the Hyprland stack and dev shell, then runs the existing `danmwallace.fedora.hyprland` Ansible role *inside the build* with its dotfile output pointed at `/etc/skel`. `bootc-image-builder` turns the pushed image into a qcow2, which the existing `libvirt_vm` OpenTofu module clones into a VM. cloud-init (added to the image) creates the `dwallace` user and sets the static IP, exactly as it does for every other srv01 VM.

**Tech Stack:** podman/buildah, bootc 1.16, dnf5 + COPR, ansible-core 2.20 (build-time only), bootc-image-builder, OpenTofu 1.8 + dmacvicar/libvirt 0.9.8, cloud-init, just, skopeo, molecule.

**Spec:** `docs/superpowers/specs/2026-10-03-atomic-hyprland-design.md` (this repo). Read it first. Phase 1 is section "Phase 1" of the spec. No NVIDIA, no Quadlets, no CI in this plan.

## Global Constraints

- Base image: `ghcr.io/ublue-os/base-main:44` pinned by digest in `build/images.env`. Current digest `sha256:69c8d37d52ea3cb9ec65cede1a1428a9df296341c7ac4556f9c9b14d93ce614f`, kernel `7.2.8-200.fc44.x86_64`.
- Akmods image (checked, not installed, in this phase): `ghcr.io/ublue-os/akmods-nvidia-open:main-44` digest `sha256:6e3cb82b2253b039e95492db552f065fabfee58bdcb40d0264df858d6f570dd0`, kernel `7.2.8-200.fc44.x86_64`.
- Image name: `ghcr.io/danmwallace/atomic-hyprland`, tags `44` and `44-<YYYYMMDD>-<shortsha>`.
- COPRs enabled only inside the build and disabled before the image is finalised: `lionheartp/Hyprland`, `atim/starship`, `atim/lazygit`. Nothing else installs from COPR on the running system.
- Secrets never go in the image or the repo. The policy entry added in this phase is `insecureAcceptAnything` for our own registry path only, replaced by sigstore in Phase 3.
- Shell is elvish. The role's `fish` package is dropped; `fish` must not appear in any package list.
- Packages dropped from the role: `picom`, `flameshot`, `fish`, `nwg-dock-hyprland` (not packaged for Fedora 44 in Fedora or the lionheartp COPR; the `nightishaman/nwg-shell` COPR has it if Dan wants it back later).
- Role defaults keep today's behaviour: `hyprland_home_dir` defaults to `/home/{{ hyprland_user }}`, `hyprland_manage_copr` and `hyprland_manage_services` default `true`. Only the image build flips them.
- Every sudo step (bootc-image-builder, `tofu apply`) is announced and confirmed with Dan before running. Nothing in this plan deletes or modifies an existing VM.
- Code style: 2-space YAML/HCL/Markdown, 4-space shell, LF, trailing newline, no trailing whitespace. Ansible: FQCN, desired-state task names, idempotent.
- Commits: Conventional Commits, imperative, first line ≤ 72 chars, end with the session attribution lines.

## Review Focus

1. **Running the role as root with no `$USER` in the environment.** The role's `hyprland_user` default reads `ansible_facts.env.USER`, which is unset in a podman build. The build playbook must set `hyprland_user` explicitly; Task 1's skel molecule scenario sets it too. Test pinned in Task 1 (converge with `hyprland_user: root`).
2. **Build must fail, not silently skip, on a kernel mismatch.** `check-kernel-match.sh` must exit non-zero when labels differ. Negative test pinned in Task 3 (run against `akmods-nvidia-open:main-43`, expect exit 1).
3. **The dotfile sync must never touch `~/.config/hypr/local.conf`.** Pinned in Task 4's test (write a sentinel into local.conf, sync twice, sentinel survives).
4. **The sync must be a no-op when the stamp matches** (login should not rewrite a file the user edited since boot). Pinned in Task 4's test (second run prints "up to date" and leaves a modified hyprland.conf alone).
5. **The image must not ship enabled COPR repos or ansible-core.** A user running `dnf` in a distrobox is unaffected, but `bootc upgrade` and lint should see a clean `/etc/yum.repos.d`. Pinned in Task 3's smoke test.

---

## Before you start (Dan, interactive, not scripted)

```elvish
sudo dnf install just virt-viewer
gh auth refresh -h github.com -s write:packages,read:packages
```

Why: `just` drives the local loop; `virt-viewer` shows the VM's VNC console; podman needs a token with `write:packages` to push to ghcr.io, and the current gh token only has `repo,workflow`.

Known preconditions, verified 2026-10-03: podman 5.x, skopeo, tofu, ansible-core 2.21, molecule 26.4, ansible-lint are installed; `az login` is current enough for the tofu azurerm backend; SSH to `dwallace@10.10.99.4` (srv01) works with agent.

---

### Task 1: `danmwallace.fedora.hyprland` learns skel mode and build toggles

**Files:**
- Modify: `~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora/roles/hyprland/defaults/main.yml`
- Modify: `.../roles/hyprland/vars/main.yml`
- Modify: `.../roles/hyprland/tasks/main.yml`
- Modify: `.../roles/hyprland/templates/home/config/hypr/hyprland.conf.j2`
- Modify: `.../roles/hyprland/meta/argument_specs.yml`
- Modify: `.../roles/hyprland/meta/main.yml` (add platform version 44)
- Create: `.../roles/hyprland/molecule/skel/molecule.yml`, `create.yml`, `destroy.yml`, `converge.yml`, `verify.yml`, `inventory/hosts.yml`

**Interfaces:**
- Produces role variables consumed by Task 3's `build/playbook.yml`:
  - `hyprland_home_dir` (str, default `/home/{{ hyprland_user }}`): directory that receives `.config/...`.
  - `hyprland_manage_copr` (bool, default `true`): when false the role does not touch COPR.
  - `hyprland_manage_services` (bool, default `true`): when false the role neither starts/enables sddm nor changes the default target.
  - Rendered file `{{ hyprland_home_dir }}/.config/hypr/local.conf` (empty, never overwritten) sourced last by `hyprland.conf`.

Work on a branch in the collection repo:

```elvish
cd ~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora
git switch -c dw/skel-mode
```

- [ ] **Step 1: Write the failing molecule `skel` scenario**

`molecule/skel/molecule.yml`:

```yaml
---
dependency:
  name: galaxy
scenario:
  test_sequence:
    - dependency
    - destroy
    - create
    - converge
    - idempotence
    - verify
    - cleanup
    - destroy
```

`molecule/skel/create.yml` (plain container, no systemd, which is exactly what a podman build looks like):

```yaml
---
- name: Create molecule instance
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Start hyprland-skel container
      containers.podman.podman_container:
        name: hyprland-skel
        image: registry.fedoraproject.org/fedora:44
        state: started
        command: sleep infinity
```

`molecule/skel/destroy.yml`:

```yaml
---
- name: Destroy molecule instance
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Remove hyprland-skel container
      containers.podman.podman_container:
        name: hyprland-skel
        state: absent
```

`molecule/skel/inventory/hosts.yml`:

```yaml
---
molecule:
  hosts:
    hyprland-skel:
      ansible_connection: containers.podman.podman
```

`molecule/skel/converge.yml` (mirrors the Containerfile: COPR enabled by dnf, role told not to manage it or services):

```yaml
---
- name: Converge in skel mode
  hosts: molecule
  gather_facts: true
  tasks:
    - name: Ensure dnf5 copr plugin and python bindings are present
      ansible.builtin.raw: dnf -y install dnf5-plugins python3-libdnf5
      changed_when: false

    - name: Ensure the Hyprland COPR is enabled the way the image build does it
      ansible.builtin.command: dnf -y copr enable lionheartp/Hyprland
      args:
        creates: /etc/yum.repos.d/_copr:copr.fedorainfracloud.org:lionheartp:Hyprland.repo

    - name: Apply hyprland role in skel mode
      ansible.builtin.include_role:
        name: danmwallace.fedora.hyprland
      vars:
        hyprland_user: root
        hyprland_home_dir: /etc/skel
        hyprland_manage_copr: false
        hyprland_manage_services: false
        hyprland_theme: nord
```

`molecule/skel/verify.yml`:

```yaml
---
- name: Verify skel mode
  hosts: molecule
  gather_facts: false
  tasks:
    - name: Stat files rendered into /etc/skel
      ansible.builtin.stat:
        path: "{{ item }}"
      loop:
        - /etc/skel/.config/hypr/hyprland.conf
        - /etc/skel/.config/hypr/hyprlock.conf
        - /etc/skel/.config/hypr/local.conf
        - /etc/skel/.config/waybar/config
        - /etc/skel/.config/alacritty/alacritty.toml
      register: skel_files

    - name: Assert skel files exist and are root-owned
      ansible.builtin.assert:
        that:
          - item.stat.exists
          - item.stat.isreg
          - item.stat.pw_name == 'root'
      loop: "{{ skel_files.results }}"
      loop_control:
        label: "{{ item.item }}"

    - name: Read rendered hyprland.conf
      ansible.builtin.slurp:
        src: /etc/skel/.config/hypr/hyprland.conf
      register: skel_hyprland_conf

    - name: Assert hyprland.conf sources local.conf last
      ansible.builtin.assert:
        that:
          - "(skel_hyprland_conf.content | b64decode).rstrip().endswith('source = ~/.config/hypr/local.conf')"

    - name: Stat things the role must NOT have done in this mode
      ansible.builtin.stat:
        path: "{{ item }}"
      loop:
        - /etc/systemd/system/display-manager.service
        - /home/root
      register: skel_forbidden

    - name: Assert services and a home dir were not touched
      ansible.builtin.assert:
        that: not item.stat.exists
      loop: "{{ skel_forbidden.results }}"
      loop_control:
        label: "{{ item.item }}"
```

- [ ] **Step 2: Run the scenario to verify it fails**

Run: `cd ~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora; molecule test -s skel`
Expected: FAIL during converge. The role ignores `hyprland_home_dir` today, writes to `/home/root`, and the `local.conf` stat fails in verify. (If it fails earlier at "Enable and start SDDM service" because there is no systemd in the container, that is the same gap: `hyprland_manage_services` does not exist yet.)

- [ ] **Step 3: Add the defaults and derived vars**

`defaults/main.yml`:

```yaml
# SPDX-License-Identifier: MIT
---
# defaults file for hyprland

hyprland_user: "{{ ansible_facts['env']['USER'] }}"
hyprland_theme: "nord"

# Directory that receives the rendered .config tree. Point at /etc/skel to
# render a template home for users created later (used by image builds).
hyprland_home_dir: "/home/{{ hyprland_user }}"

# Set false when the caller has already enabled the lionheartp/Hyprland COPR
# (image builds do it with `dnf copr enable` before running the role).
hyprland_manage_copr: true

# Set false where systemd is not running (container image builds). The role
# then neither enables/starts sddm nor changes the default target.
hyprland_manage_services: true
```

`vars/main.yml`:

```yaml
# SPDX-License-Identifier: MIT
---
# vars file for hyprland

# In skel mode the rendered files belong to root; otherwise to the target user.
hyprland_skel_mode: "{{ hyprland_home_dir == '/etc/skel' }}"
hyprland_file_owner: "{{ 'root' if hyprland_skel_mode else hyprland_user }}"
```

- [ ] **Step 4: Rewrite tasks/main.yml to honour the new variables**

Replace the file with the following. Changes versus today: COPR task gated; package list deduplicated and minus `picom`, `flameshot`, `fish`, `nwg-dock-hyprland`, plus the packages the shipped `hyprland.conf` already autostarts (`swaybg`, `cliphist`, `network-manager-applet`, `gnome-keyring`, `xdg-desktop-portal-gtk`, `xdg-desktop-portal-hyprland`, `qt6ct`, `qt5-qtwayland`, `qt6-qtwayland`) and the X11 SDDM greeter (`sddm-x11`, Fedora's default greeter for non-Plasma setups); service tasks gated; every `/home/{{ hyprland_user }}` becomes `{{ hyprland_home_dir }}`; owner/group/become_user use `hyprland_file_owner`; a new `local.conf` task.

```yaml
# SPDX-License-Identifier: MIT
---
# tasks file for hyprland

- name: "Load theme variables"
  ansible.builtin.include_vars:
    file: "themes/{{ hyprland_theme }}.yml"

- name: "Ensure lionheartp/Hyprland COPR repository is enabled"
  community.general.copr:
    name: lionheartp/Hyprland
    state: enabled
  become: true
  when: hyprland_manage_copr

- name: "Ensure Hyprland and its supporting packages are installed"
  ansible.builtin.dnf:
    name:
      - hyprland
      - hyprpaper
      - hyprpicker
      - hypridle
      - hyprlock
      - hyprpolkitagent
      - xdg-desktop-portal-hyprland
      - xdg-desktop-portal-gtk
      - sddm
      - sddm-x11
      - waybar
      - alacritty
      - wofi
      - nwg-drawer
      - waypaper
      - swaybg
      - cliphist
      - wl-clipboard
      - grim
      - slurp
      - pamixer
      - pavucontrol
      - light
      - bluez
      - bluez-tools
      - blueman
      - tuned
      - tuned-ppd
      - network-manager-applet
      - NetworkManager-wifi
      - nm-connection-editor-desktop
      - gnome-keyring
      - qt6ct
      - qt5-qtwayland
      - qt6-qtwayland
      - cups-pk-helper
      - podman
      - nautilus
      - simple-scan
      - firefox
      - libreoffice
      - thunderbird
      - alsa-sof-firmware
      - alsa-utils
      - gvfs
      - gvfs-mtp
    state: present
  become: true

- name: "Ensure SDDM is enabled and running"
  ansible.builtin.systemd_service:
    name: sddm
    enabled: true
    state: started
  become: true
  when: hyprland_manage_services

- name: "Ensure the default systemd target is graphical"
  ansible.builtin.command: "systemctl set-default graphical.target"
  become: true
  register: hyprland_set_default
  changed_when: "'Created symlink' in (hyprland_set_default.stderr | default(''))"
  when: hyprland_manage_services

- name: "Ensure config directories exist"
  ansible.builtin.file:
    path: "{{ hyprland_home_dir }}/.config/{{ item }}"
    state: directory
    owner: "{{ hyprland_file_owner }}"
    group: "{{ hyprland_file_owner }}"
    mode: "0755"
  become: true
  become_user: "{{ hyprland_file_owner }}"
  loop:
    - hypr
    - hypr/scripts
    - waybar
    - alacritty
    - wofi
    - nwg-drawer
    - nwg-dock-hyprland

- name: "Ensure static Hyprland configuration files are present"
  ansible.builtin.copy:
    src: "{{ item.src }}"
    dest: "{{ hyprland_home_dir }}/.config/{{ item.dest }}"
    owner: "{{ hyprland_file_owner }}"
    group: "{{ hyprland_file_owner }}"
    mode: "0755"
  become: true
  become_user: "{{ hyprland_file_owner }}"
  loop:
    - src: home/dwallace/config/hypr/xdg-portal-hyprland
      dest: hypr/xdg-portal-hyprland
    - src: home/dwallace/config/hypr/scripts/sleep.sh
      dest: hypr/scripts/sleep.sh
    - src: home/dwallace/config/wofi/config
      dest: wofi/config

- name: "Ensure themed configuration files are rendered"
  ansible.builtin.template:
    src: "{{ item.src }}"
    dest: "{{ hyprland_home_dir }}/.config/{{ item.dest }}"
    owner: "{{ hyprland_file_owner }}"
    group: "{{ hyprland_file_owner }}"
    mode: "0644"
  become: true
  become_user: "{{ hyprland_file_owner }}"
  loop:
    - src: home/config/hypr/hyprland.conf.j2
      dest: hypr/hyprland.conf
    - src: home/config/hypr/hyprlock.conf.j2
      dest: hypr/hyprlock.conf
    - src: home/config/waybar/style.css.j2
      dest: waybar/style.css
    - src: home/config/waybar/config.j2
      dest: waybar/config
    - src: home/config/alacritty/alacritty.toml.j2
      dest: alacritty/alacritty.toml
    - src: home/config/wofi/style.css.j2
      dest: wofi/style.css
    - src: home/config/wofi/style-power.css.j2
      dest: wofi/style-power.css
    - src: home/config/wofi/style-run.css.j2
      dest: wofi/style-run.css
    - src: home/config/nwg-drawer/drawer.css.j2
      dest: nwg-drawer/drawer.css
    - src: home/config/nwg-dock-hyprland/style.css.j2
      dest: nwg-dock-hyprland/style.css

- name: "Ensure a per-machine local.conf exists (never overwritten)"
  ansible.builtin.copy:
    content: "# Per-machine Hyprland overrides. Sourced last by hyprland.conf; never managed.\n"
    dest: "{{ hyprland_home_dir }}/.config/hypr/local.conf"
    owner: "{{ hyprland_file_owner }}"
    group: "{{ hyprland_file_owner }}"
    mode: "0644"
    force: false
  become: true
  become_user: "{{ hyprland_file_owner }}"

- name: "Ensure SDDM themes are present"
  ansible.builtin.copy:
    src: "usr/share/sddm/themes/"
    dest: "/usr/share/sddm/themes/"
    mode: "0755"
  become: true

- name: "Ensure SDDM configuration is present"
  ansible.builtin.copy:
    src: "etc/sddm.conf.d/"
    dest: "/etc/sddm.conf.d/"
    mode: "0644"
  become: true
```

- [ ] **Step 5: Make hyprland.conf source local.conf last and drop the dock autostart**

In `templates/home/config/hypr/hyprland.conf.j2`, replace the two lines

```
exec-once = nwg-dock-hyprland -x -o "eDP-1"
exec-once = nwg-dock-hyprland -x -o "DP-7"
```

with

```
# nwg-dock-hyprland is not packaged for Fedora 44; re-enable via the
# nightishaman/nwg-shell COPR if wanted.
# exec-once = nwg-dock-hyprland -x -o "eDP-1"
# exec-once = nwg-dock-hyprland -x -o "DP-7"
```

and append to the very end of the file (after the lid-switch binds), with one blank line before it:

```

#############################
### PER-MACHINE OVERRIDES ###
#############################

# Keep machine-specific settings (VM monitor, NVIDIA env, etc.) here.
# This file is never managed by the role or the image.
source = ~/.config/hypr/local.conf
```

- [ ] **Step 6: Update argument_specs and meta**

Append to `options:` in `meta/argument_specs.yml`:

```yaml
      hyprland_home_dir:
        description:
          - Directory that receives the rendered .config tree. Defaults to the target
            user's home. Set to /etc/skel to render a template home for users created
            later, for example inside a bootc image build; files are then root-owned.
        type: str
        required: false
        default: "/home/{{ hyprland_user }}"
      hyprland_manage_copr:
        description:
          - Whether the role enables the lionheartp/Hyprland COPR. Set false when the
            caller enabled it already (image builds use dnf copr enable).
        type: bool
        required: false
        default: true
      hyprland_manage_services:
        description:
          - Whether the role enables and starts sddm and sets graphical.target as the
            default. Set false where systemd is not running, such as a container build.
        type: bool
        required: false
        default: true
```

In `meta/main.yml` change `versions: ["41", "42", "43"]` to `versions: ["42", "43", "44"]`.

- [ ] **Step 7: Run the skel scenario to verify it passes**

Run: `molecule test -s skel`
Expected: PASS, including the idempotence step (second converge reports no changes; `local.conf` uses `force: false` so it is not rewritten).

- [ ] **Step 8: Run the existing default scenario and lint**

Run: `molecule test -s default; ansible-lint`
Expected: default scenario still converges on fedora:42 with the new package list (it needs the COPR, which the role still manages there) and `ansible-lint` reports 0 failures. If `community.general.copr` fails on the dnf5-only fedora:42 container, replace the default scenario's reliance on it the same way the skel scenario does (raw `dnf -y copr enable`, `hyprland_manage_copr: false`) and note it in the CHANGELOG under Fixed.

- [ ] **Step 9: Commit**

```bash
git add roles/hyprland
git commit -m "feat(hyprland): add skel mode, copr/service toggles, local.conf

Allows the role to run inside a bootc image build: hyprland_home_dir can
point at /etc/skel, and hyprland_manage_copr / hyprland_manage_services
let the caller own the COPR and systemd steps. hyprland.conf now sources
~/.config/hypr/local.conf last for per-machine overrides. Drops picom,
flameshot, fish and nwg-dock-hyprland (unpackaged on Fedora 44); adds the
packages the shipped hyprland.conf already autostarts and sddm-x11.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 2: Release `danmwallace.fedora` 1.1.0

**Files:**
- Modify: `.../fedora/galaxy.yml` (version `1.0.1` to `1.1.0`)
- Modify: `.../fedora/CHANGELOG.md`
- Modify: `.../fedora/README.md` (Requirements line: Fedora 42, 43, or 44)
- Modify: `.../fedora/roles/hyprland/README.md` (variables table, requirements)

**Interfaces:**
- Produces git tag `v1.1.0` on `main` of `github.com/danmwallace/ansible-collection-fedora`, which Task 3's `build/requirements.yml` pins.

- [ ] **Step 1: CHANGELOG entry**

Under `## [Unreleased]` leave nothing; add above `## [1.0.1]`:

```markdown
## [1.1.0] - 2026-10-03

### Added

- `hyprland_home_dir`, `hyprland_manage_copr`, `hyprland_manage_services` so the
  `hyprland` role can run inside a bootc image build (skel mode).
- `~/.config/hypr/local.conf`, created once and sourced last by `hyprland.conf`,
  for per-machine overrides.
- Molecule scenario `skel` covering the image-build mode.
- Packages the shipped `hyprland.conf` already autostarts: swaybg, cliphist,
  network-manager-applet, gnome-keyring, xdg-desktop-portal-gtk,
  xdg-desktop-portal-hyprland, qt6ct, qt5-qtwayland, qt6-qtwayland; and the
  X11 SDDM greeter (sddm-x11).

### Changed

- Supported platforms: Fedora 42, 43, 44.

### Removed

- Packages picom (X11-only), flameshot (grim+slurp cover it), fish (shell is
  elvish), nwg-dock-hyprland (not packaged for Fedora 44). The dock's
  `exec-once` lines are commented out.
```

- [ ] **Step 2: README tables**

In `roles/hyprland/README.md` add three rows to the variables table:

```markdown
| `hyprland_home_dir`        | str  | no       | `/home/{{ hyprland_user }}`           | Directory that receives `.config/`. Use `/etc/skel` for image builds (files become root-owned). |
| `hyprland_manage_copr`     | bool | no       | `true`                                | Enable the `lionheartp/Hyprland` COPR. Set `false` if the caller already did. |
| `hyprland_manage_services` | bool | no       | `true`                                | Enable/start `sddm` and set `graphical.target`. Set `false` without a running systemd. |
```

and add under Example Playbook a second example:

```yaml
# Inside a container/bootc image build (no systemd running, COPR enabled by dnf):
- hosts: localhost
  connection: local
  roles:
    - role: danmwallace.fedora.hyprland
      vars:
        hyprland_user: root
        hyprland_home_dir: /etc/skel
        hyprland_manage_copr: false
        hyprland_manage_services: false
```

Change every "Fedora (41, 42, or 43)" in both READMEs to "Fedora (42, 43, or 44)".

- [ ] **Step 3: Bump version, lint, commit, PR, merge, tag**

Set `version: 1.1.0` in `galaxy.yml`. Then:

```bash
ansible-lint
git add galaxy.yml CHANGELOG.md README.md roles/hyprland/README.md
git commit -m "chore: release v1.1.0 — skel mode for image builds

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/skel-mode
gh pr create --fill --title "feat(hyprland): skel mode for bootc image builds (v1.1.0)"
```

Wait for the CI workflow (ansible-lint, build-collection, release-tag audit) to pass, then:

```bash
gh pr merge --squash --delete-branch
git switch main && git pull
git tag -a v1.1.0 -m "v1.1.0"
git push origin v1.1.0
```

Expected: the `Release` workflow publishes 1.1.0 to Galaxy (tag matches galaxy.yml). Verify with `gh run list --workflow Release --limit 1` showing success. Galaxy availability is not required by Task 3, which installs the collection from the git tag.

---

### Task 3: Image build scaffolding, smoke test, kernel check

**Files (all in `~/Code/atomic-hyprland`):**
- Create: `tests/image-smoke.sh`
- Create: `build/images.env`
- Create: `build/check-kernel-match.sh`
- Create: `build/packages.txt`
- Create: `build/10-packages.sh`, `build/20-hyprland-role.sh`, `build/30-policy.sh`, `build/40-finalize.sh`, `build/90-cleanup.sh`
- Create: `build/playbook.yml`, `build/requirements.yml`
- Create: `Containerfile`
- Create: `justfile`
- Modify: `.gitignore` (add `output/`, already there, and `*.log`)

**Interfaces:**
- Produces image `ghcr.io/danmwallace/atomic-hyprland:44` locally (rootless podman store) with:
  - `/etc/skel/.config/hypr/{hyprland.conf,local.conf,...}` rendered by the role (nord theme by default, `THEME` build arg).
  - `/usr/share/atomic-hyprland/stamp` containing the `IMAGE_VERSION` build arg, and `/usr/share/atomic-hyprland/skel/` a copy of `/etc/skel`. Task 4 adds `managed-files.txt` beside them.
  - sddm enabled, `graphical.target` default, policy entry for our registry.
- Produces `just` recipes: `build`, `test`, `lint`, `check-kernel`, `push`, `qcow2` (Task 6 fills in qcow2).

- [ ] **Step 1: Write the smoke test first**

`tests/image-smoke.sh`:

```bash
#!/usr/bin/bash
# Runs INSIDE the built image: podman run --rm -v ./tests:/tests:ro,Z IMAGE bash /tests/image-smoke.sh
set -uo pipefail

fail=0
check() {
    if "$@" >/dev/null 2>&1; then
        echo "ok    $*"
    else
        echo "FAIL  $*"
        fail=1
    fi
}

check rpm -q hyprland hyprlock hypridle hyprpaper xdg-desktop-portal-hyprland
check rpm -q sddm sddm-x11 waybar wofi alacritty swaybg cliphist
check rpm -q elvish starship lazygit fzf ripgrep fd-find bat git gh jq yq uv distrobox
check rpm -q cloud-init qemu-guest-agent
check bash -c '! rpm -q fish'
check bash -c '! rpm -q ansible-core'
check test -f /etc/skel/.config/hypr/hyprland.conf
check test -f /etc/skel/.config/hypr/local.conf
check grep -q '^source = ~/.config/hypr/local.conf' /etc/skel/.config/hypr/hyprland.conf
check test -f /usr/share/wayland-sessions/hyprland.desktop
check test -L /etc/systemd/system/display-manager.service
check test "$(readlink -f /etc/systemd/system/default.target)" = /usr/lib/systemd/system/graphical.target
check grep -q '^/usr/bin/elvish$' /etc/shells
check jq -e '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"][0].type == "insecureAcceptAnything"' /etc/containers/policy.json
check bash -c '! grep -ls "^enabled=1" /etc/yum.repos.d/_copr*.repo'
check test -s /usr/share/atomic-hyprland/stamp
check test -f /usr/share/atomic-hyprland/skel/.config/hypr/hyprland.conf
check bash -c '! test -e /var/roothome/.ansible'
check bash -c 'test -z "$(ls -A /var/cache 2>/dev/null)"'

exit "$fail"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/Code/atomic-hyprland; podman run --rm -v ./tests:/tests:ro,Z ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/image-smoke.sh`
Expected: error, image does not exist locally yet. (After Step 7 this same command is the test.)

- [ ] **Step 3: Pin images and write the kernel check with its negative test**

`build/images.env`:

```bash
# Pinned inputs. Bump deliberately; `just check-kernel` must pass after a bump.
BASE_IMAGE=ghcr.io/ublue-os/base-main:44@sha256:69c8d37d52ea3cb9ec65cede1a1428a9df296341c7ac4556f9c9b14d93ce614f
AKMODS_IMAGE=ghcr.io/ublue-os/akmods-nvidia-open:main-44@sha256:6e3cb82b2253b039e95492db552f065fabfee58bdcb40d0264df858d6f570dd0
```

`build/check-kernel-match.sh`:

```bash
#!/usr/bin/bash
# Fail unless the base image and the NVIDIA akmods image were built for the
# same kernel. Both ublue images carry the kernel in the ostree.linux label.
# Usage: check-kernel-match.sh [BASE_IMAGE] [AKMODS_IMAGE]  (defaults: build/images.env)
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=images.env
source "${here}/images.env"
base="${1:-${BASE_IMAGE}}"
akmods="${2:-${AKMODS_IMAGE}}"

kernel_of() {
    skopeo inspect --no-tags "docker://$1" | jq -r '.Labels["ostree.linux"] // empty'
}

base_kernel="$(kernel_of "${base}")"
akmods_kernel="$(kernel_of "${akmods}")"

if [[ -z "${base_kernel}" || -z "${akmods_kernel}" ]]; then
    echo "check-kernel: could not read ostree.linux label (base='${base_kernel}' akmods='${akmods_kernel}')" >&2
    exit 2
fi
if [[ "${base_kernel}" != "${akmods_kernel}" ]]; then
    echo "check-kernel: MISMATCH base=${base_kernel} akmods=${akmods_kernel}" >&2
    exit 1
fi
echo "check-kernel: ok ${base_kernel}"
```

Run: `chmod +x build/check-kernel-match.sh; build/check-kernel-match.sh`
Expected: `check-kernel: ok 7.2.8-200.fc44.x86_64`, exit 0.

Run the negative case: `build/check-kernel-match.sh "" ghcr.io/ublue-os/akmods-nvidia-open:main-43; echo "exit=$?"`
Expected: a MISMATCH line and `exit=1`. (Passing `""` as the first arg falls back to the pinned base because of `${1:-...}`.)

- [ ] **Step 4: Package list and build scripts**

`build/packages.txt` (one per line, `#` comments allowed; the Hyprland stack is installed by the role, not here):

```
# dev shell
elvish
starship
fzf
lazygit
ripgrep
fd-find
bat
git
gh
jq
yq
make
nodejs
npm
python3
python3-pip
uv
skopeo
# VM / first-boot support (cloud-init creates the user and sets the static IP
# on srv01 VMs; harmless elsewhere and disabled by Ansible on bare metal)
cloud-init
qemu-guest-agent
# used by the dotfile sync and hermes_native later
rsync
curl
```

`build/10-packages.sh`:

```bash
#!/usr/bin/bash
set -euo pipefail

# COPRs are enabled only for the build; 90-cleanup.sh disables them again.
dnf -y copr enable atim/starship
dnf -y copr enable atim/lazygit
dnf -y copr enable lionheartp/Hyprland

mapfile -t packages < <(grep -vE '^\s*(#|$)' /tmp/build/packages.txt)
dnf -y install --setopt=install_weak_deps=False "${packages[@]}"

# Build-time only; removed in 90-cleanup.sh.
dnf -y install --setopt=install_weak_deps=False ansible-core python3-libdnf5
```

`build/requirements.yml`:

```yaml
---
# Pinned to the git tag rather than Galaxy so the build does not wait on a
# Galaxy publish and so a rebuild months later gets the same role.
collections:
  - name: https://github.com/danmwallace/ansible-collection-fedora.git
    type: git
    version: v1.1.0
  - name: community.general
    version: ">=8.0.0"
```

`build/playbook.yml`:

```yaml
---
- name: Render the Hyprland desktop into the image
  hosts: localhost
  connection: local
  gather_facts: true
  roles:
    - role: danmwallace.fedora.hyprland
      vars:
        # $USER is unset inside podman build; the role's default would fail.
        hyprland_user: root
        hyprland_home_dir: /etc/skel
        hyprland_manage_copr: false
        hyprland_manage_services: false
```

`build/20-hyprland-role.sh`:

```bash
#!/usr/bin/bash
set -euo pipefail
theme="${1:?theme}"

# Keep every Ansible artefact under /tmp/build so nothing lands in
# /var/roothome (which bootc lint and the smoke test both reject).
export ANSIBLE_HOME=/tmp/build/ansible
export ANSIBLE_LOCAL_TEMP=/tmp/build/ansible/tmp
export ANSIBLE_COLLECTIONS_PATH=/tmp/build/collections
export ANSIBLE_NOCOWS=1

ansible-galaxy collection install -p /tmp/build/collections -r /tmp/build/requirements.yml
ansible-playbook -c local -i localhost, /tmp/build/playbook.yml -e "hyprland_theme=${theme}"
```

`build/30-policy.sh`:

```bash
#!/usr/bin/bash
# Phase 1: let bootc pull our own image unsigned. Phase 3 replaces this entry
# with sigstoreSigned. The ublue base ships default=reject, so without an
# entry `bootc upgrade` would refuse ghcr.io/danmwallace/atomic-hyprland.
set -euo pipefail
policy=/etc/containers/policy.json
tmp="$(mktemp)"
jq '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"] = [{"type": "insecureAcceptAnything"}]' "${policy}" > "${tmp}"
install -m 0644 "${tmp}" "${policy}"
rm -f "${tmp}"
```

`build/40-finalize.sh`:

```bash
#!/usr/bin/bash
set -euo pipefail
version="${1:?image version}"

systemctl enable sddm.service
systemctl set-default graphical.target

# Pristine copy of the rendered skel plus a stamp, for the login-time sync
# (Task 4) and for `bootc` users created before an image update.
install -d /usr/share/atomic-hyprland
cp -a /etc/skel /usr/share/atomic-hyprland/skel
printf '%s\n' "${version}" > /usr/share/atomic-hyprland/stamp
```

`build/90-cleanup.sh`:

```bash
#!/usr/bin/bash
set -euo pipefail

dnf -y remove ansible-core python3-libdnf5
dnf -y copr disable atim/starship
dnf -y copr disable atim/lazygit
dnf -y copr disable lionheartp/Hyprland
dnf clean all

rm -rf /tmp/build /tmp/* /var/cache/* /var/log/* /var/roothome/.ansible /var/roothome/.cache
# /var must be empty-ish for bootc lint; list anything it still complains about here.

bootc container lint
```

- [ ] **Step 5: Containerfile**

```dockerfile
# atomic-hyprland: Fedora 44 bootc image with Hyprland, built on Universal Blue base-main.
ARG BASE_IMAGE=ghcr.io/ublue-os/base-main:44
FROM ${BASE_IMAGE}

ARG THEME=nord
ARG NVIDIA=0
ARG IMAGE_VERSION=dev

COPY build/ /tmp/build/
COPY files/ /

RUN /tmp/build/10-packages.sh
RUN /tmp/build/20-hyprland-role.sh "${THEME}"
RUN if [ "${NVIDIA}" = "1" ]; then echo "NVIDIA layer arrives in Phase 4; build with NVIDIA=0" >&2; exit 1; fi
RUN /tmp/build/30-policy.sh && /tmp/build/40-finalize.sh "${IMAGE_VERSION}"
RUN /tmp/build/90-cleanup.sh

LABEL org.opencontainers.image.title="atomic-hyprland" \
      org.opencontainers.image.source="https://github.com/danmwallace/atomic-hyprland" \
      org.opencontainers.image.version="${IMAGE_VERSION}"
```

Create an empty `files/.keep` so the `COPY files/ /` line has a source (Task 4 adds real files). `chmod +x build/*.sh`.

- [ ] **Step 6: justfile**

```just
set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := false

image   := "ghcr.io/danmwallace/atomic-hyprland"
tag     := "44"
version := `date -u +%Y%m%d` + "-" + `git rev-parse --short HEAD`

# Build the image locally (rootless podman). THEME: nord | tokyo-night | monochrome
build theme="nord" nvidia="0":
    source build/images.env && podman build \
        --build-arg BASE_IMAGE="$BASE_IMAGE" \
        --build-arg THEME={{theme}} \
        --build-arg NVIDIA={{nvidia}} \
        --build-arg IMAGE_VERSION={{version}} \
        -t {{image}}:{{tag}} -t {{image}}:{{tag}}-{{version}} .

# Run the in-image smoke tests
test:
    podman run --rm -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/image-smoke.sh
    podman run --rm -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/test-sync-dotfiles.sh

# bootc's own lint, standalone
lint:
    podman run --rm {{image}}:{{tag}} bootc container lint

# Base and akmods must be built for the same kernel
check-kernel:
    build/check-kernel-match.sh

# Push both tags to ghcr.io (needs: gh auth token | podman login ghcr.io -u danmwallace --password-stdin)
push:
    podman push {{image}}:{{tag}}
    podman push {{image}}:{{tag}}-{{version}}

# Build a qcow2 with bootc-image-builder. Needs sudo (root podman). See Task 6.
qcow2:
    @echo "filled in by Task 6"
```

- [ ] **Step 7: Build and run the smoke test**

Run: `just check-kernel && just build && just test 2>&1 | grep -v test-sync-dotfiles`
Expected: build completes (first build pulls the base and installs roughly 1.5 GB of packages; allow 10 to 20 minutes), the `bootc container lint` step inside `90-cleanup.sh` passes, and `image-smoke.sh` prints only `ok` lines and exits 0. The `test-sync-dotfiles.sh` line fails until Task 4; ignore it here.

If lint reports leftover paths under `/var`, add them to the `rm -rf` line in `90-cleanup.sh` and rebuild. If `ansible-galaxy` cannot reach GitHub, the build host has no network in the build stage; rerun with `podman build --network host`.

- [ ] **Step 8: Commit**

```bash
git add Containerfile justfile build tests files/.keep .gitignore
git commit -m "feat: build the Hyprland bootc image on ublue base-main

Runs danmwallace.fedora.hyprland (v1.1.0, skel mode) inside the build,
adds the dev shell and cloud-init, enables sddm, and ships a policy entry
for our own registry. Includes an in-image smoke test and a kernel-label
check between base-main and akmods-nvidia-open.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 4: Login-time dotfile sync (stamp-based, never touches local.conf)

**Files:**
- Create: `tests/test-sync-dotfiles.sh`
- Create: `files/usr/libexec/atomic-hyprland/sync-dotfiles`
- Create: `files/usr/lib/systemd/user/atomic-hyprland-dotfiles.service`
- Modify: `build/40-finalize.sh` (generate `managed-files.txt`, enable the user unit globally)

**Interfaces:**
- Consumes `/usr/share/atomic-hyprland/{stamp,skel/}` from Task 3.
- Produces `/usr/share/atomic-hyprland/managed-files.txt` (paths relative to `$HOME`, one per line, excludes `.config/hypr/local.conf`), `/usr/libexec/atomic-hyprland/sync-dotfiles` (honours `ATOMIC_HYPRLAND_SHARE` and `HOME` env for tests), and a user service enabled for all users.

- [ ] **Step 1: Write the failing test**

`tests/test-sync-dotfiles.sh`:

```bash
#!/usr/bin/bash
# Runs INSIDE the built image. Exercises /usr/libexec/atomic-hyprland/sync-dotfiles
# against a throwaway HOME and a throwaway copy of /usr/share/atomic-hyprland.
set -euo pipefail

sync=/usr/libexec/atomic-hyprland/sync-dotfiles
share="$(mktemp -d)"
export HOME="$(mktemp -d)"
export ATOMIC_HYPRLAND_SHARE="${share}"
cp -a /usr/share/atomic-hyprland/. "${share}/"

fail=0
expect() { if eval "$2"; then echo "ok    $1"; else echo "FAIL  $1"; fail=1; fi; }

# 1. first run populates managed files and writes the stamp
"${sync}"
expect "hyprland.conf synced" 'test -f "$HOME/.config/hypr/hyprland.conf"'
expect "waybar config synced" 'test -f "$HOME/.config/waybar/config"'
expect "stamp recorded" 'cmp -s "$share/stamp" "$HOME/.config/atomic-hyprland/stamp"'
expect "local.conf not in managed list" '! grep -qx ".config/hypr/local.conf" "$share/managed-files.txt"'

# 2. same stamp: no-op, user edits survive
echo "# user edit" >> "$HOME/.config/hypr/hyprland.conf"
printf 'monitor=Virtual-1,preferred,auto,1\n' > "$HOME/.config/hypr/local.conf"
out="$("${sync}")"
expect "second run reports up to date" '[[ "$out" == *"up to date"* ]]'
expect "user edit kept when stamp unchanged" 'grep -q "# user edit" "$HOME/.config/hypr/hyprland.conf"'

# 3. new stamp: managed files refreshed, local.conf untouched
echo "newer-build" > "${share}/stamp"
"${sync}"
expect "managed file refreshed after stamp change" '! grep -q "# user edit" "$HOME/.config/hypr/hyprland.conf"'
expect "local.conf survives resync" 'grep -q "Virtual-1" "$HOME/.config/hypr/local.conf"'
expect "new stamp recorded" 'grep -qx newer-build "$HOME/.config/atomic-hyprland/stamp"'

# 4. script mode preserved for executables
expect "sleep.sh stays executable" 'test -x "$HOME/.config/hypr/scripts/sleep.sh"'

# 5. unit is enabled for every user
expect "user unit enabled globally" 'test -L /etc/systemd/user/default.target.wants/atomic-hyprland-dotfiles.service'

exit "$fail"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `podman run --rm -v ./tests:/tests:ro,Z ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/test-sync-dotfiles.sh`
Expected: fails immediately, `/usr/libexec/atomic-hyprland/sync-dotfiles: No such file`.

- [ ] **Step 3: Write the sync script and unit**

`files/usr/libexec/atomic-hyprland/sync-dotfiles` (mode 0755):

```bash
#!/usr/bin/bash
# Copy image-managed dotfiles into $HOME when the image's stamp changed.
# Never touches ~/.config/hypr/local.conf (not in managed-files.txt).
set -euo pipefail

share="${ATOMIC_HYPRLAND_SHARE:-/usr/share/atomic-hyprland}"
home="${HOME:?HOME is not set}"
stamp_src="${share}/stamp"
stamp_dst="${home}/.config/atomic-hyprland/stamp"
manifest="${share}/managed-files.txt"

if [[ -f "${stamp_dst}" ]] && cmp -s "${stamp_src}" "${stamp_dst}"; then
    echo "atomic-hyprland dotfiles: up to date ($(cat "${stamp_src}"))"
    exit 0
fi

while IFS= read -r rel; do
    [[ -z "${rel}" || "${rel}" == \#* ]] && continue
    src="${share}/skel/${rel}"
    [[ -f "${src}" ]] || continue
    install -D -m "$(stat -c %a "${src}")" "${src}" "${home}/${rel}"
done < "${manifest}"

install -D -m 0644 "${stamp_src}" "${stamp_dst}"
echo "atomic-hyprland dotfiles: synced to $(cat "${stamp_src}")"
```

`files/usr/lib/systemd/user/atomic-hyprland-dotfiles.service`:

```ini
[Unit]
Description=Sync image-managed Hyprland dotfiles into the home directory
ConditionPathExists=/usr/share/atomic-hyprland/stamp

[Service]
Type=oneshot
ExecStart=/usr/libexec/atomic-hyprland/sync-dotfiles

[Install]
WantedBy=default.target
```

Remove `files/.keep`. Make sure the script is executable in git: `chmod 0755 files/usr/libexec/atomic-hyprland/sync-dotfiles` (git tracks the x bit; `COPY` preserves it).

- [ ] **Step 4: Generate the manifest and enable the unit at build time**

Append to `build/40-finalize.sh`:

```bash
# Files the login-time sync may overwrite. local.conf is deliberately excluded.
( cd /etc/skel && find .config -type f ! -path '.config/hypr/local.conf' | sort ) \
    > /usr/share/atomic-hyprland/managed-files.txt

systemctl --global enable atomic-hyprland-dotfiles.service
```

- [ ] **Step 5: Rebuild and run both tests**

Run: `just build && just test`
Expected: both test scripts print only `ok` lines, exit 0.

- [ ] **Step 6: Commit**

```bash
git add files build/40-finalize.sh tests/test-sync-dotfiles.sh
git rm -q --cached files/.keep 2>/dev/null || true
git commit -m "feat: sync image-managed dotfiles at login when the stamp changes

Users created from /etc/skel get the dotfiles once; this user unit refreshes
the managed files after an image update and never touches local.conf.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

---

### Task 5: GitHub repo, push the image to ghcr.io, make the package public

**Files:** none new.

**Interfaces:**
- Produces `ghcr.io/danmwallace/atomic-hyprland:44` reachable anonymously (needed by `bootc` on the VM in Phase 2 and by `bootc status` now).

- [ ] **Step 1: Create the GitHub repo and push**

```bash
cd ~/Code/atomic-hyprland
gh repo create danmwallace/atomic-hyprland --public --source=. --remote=origin --push \
  --description "Fedora bootc image: Hyprland desktop on Universal Blue base-main"
```

Expected: `origin` set, `main` pushed. Public because the container package inherits nothing from a local push and a private image would need credentials on every machine that runs `bootc upgrade`.

- [ ] **Step 2: Log podman into ghcr.io and push**

Dan must have run the `gh auth refresh` from "Before you start". Then:

```bash
gh auth token | podman login ghcr.io -u danmwallace --password-stdin
just push
skopeo inspect --no-tags docker://ghcr.io/danmwallace/atomic-hyprland:44 | jq -r '.Labels["org.opencontainers.image.version"]'
```

Expected: the version label printed matches `just --evaluate version`.

- [ ] **Step 3: Make the package public and link it to the repo (web UI, Dan)**

Open `https://github.com/users/danmwallace/packages/container/atomic-hyprland/settings`, set visibility to Public, and under "Manage Actions access" connect the `atomic-hyprland` repository. GitHub has no API for package visibility, so this is manual. Verify anonymously:

```bash
podman logout ghcr.io
skopeo inspect --no-tags docker://ghcr.io/danmwallace/atomic-hyprland:44 >/dev/null && echo public-ok
gh auth token | podman login ghcr.io -u danmwallace --password-stdin
```

Expected: `public-ok`.

---

### Task 6: qcow2 with bootc-image-builder (sudo)

**Files:**
- Modify: `justfile` (`qcow2` recipe)
- Modify: `README.md` (how to build the qcow2)

**Interfaces:**
- Produces `output/qcow2/disk.qcow2` (bootc-image-builder's fixed layout), root filesystem btrfs, no users baked in (cloud-init creates `dwallace` at first boot from the libvirt NoCloud ISO, same as every other srv01 VM).

- [ ] **Step 1: justfile recipe**

Replace the `qcow2` recipe with:

```just
# Build output/qcow2/disk.qcow2 from the pushed image. Needs root podman because
# bootc-image-builder must mount loop devices; it reads the image from root's
# container store, hence the sudo podman pull first.
qcow2:
    mkdir -p output
    sudo podman pull {{image}}:{{tag}}
    sudo podman run --rm -it --privileged --security-opt label=type:unconfined_t \
        -v ./output:/output \
        -v /var/lib/containers/storage:/var/lib/containers/storage \
        quay.io/centos-bootc/bootc-image-builder:latest \
        build --type qcow2 --rootfs btrfs --chown "$(id -u):$(id -g)" {{image}}:{{tag}}
    ls -lh output/qcow2/disk.qcow2
```

Why btrfs: Fedora's default root filesystem, and the ublue base ships no `bootc install` default so `--rootfs` is mandatory. Why pull from the registry rather than copy the rootless image: it proves the pushed artefact is what boots.

- [ ] **Step 2: Run it (confirm sudo with Dan first)**

Tell Dan: the recipe runs `sudo podman pull` and a privileged `sudo podman run` of bootc-image-builder; it writes only under `./output` and root's container store. Then:

Run: `just qcow2`
Expected: after 5 to 10 minutes, `output/qcow2/disk.qcow2` exists, roughly 3 to 5 GB, owned by dwallace. If bib complains it cannot find the image, the `--security-opt`/storage mount is wrong for this podman version; run with `--log-level debug` and check that `/var/lib/containers/storage` on the host is the root store (`sudo podman info --format '{{.Store.GraphRoot}}'`).

- [ ] **Step 3: README section and commit**

Add to `README.md`:

```markdown
## Local loop

```bash
just check-kernel   # base and akmods on the same kernel
just build          # rootless podman build, tags :44 and :44-<date>-<sha>
just test           # in-image smoke + dotfile sync tests
just push           # to ghcr.io (podman login first)
just qcow2          # sudo; output/qcow2/disk.qcow2 for the srv01 VM
```
```

```bash
git add justfile README.md
git commit -m "feat: build a qcow2 with bootc-image-builder

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push
```

---

### Task 7: `hypr-test` VM on srv01 via OpenTofu

**Files (in `~/Code/Infrastructure/tofu-homelab-cfg`):**
- Modify: `modules/libvirt_vm/variables.tf` (add `vnc_console`, `user_shell`, `package_update`)
- Modify: `modules/libvirt_vm/main.tf` (graphics/video/input blocks, pass new vars to the template)
- Modify: `modules/libvirt_vm/templates/user-data.yaml.tftpl` (`shell`, `package_update`)
- Modify: `libvirt-srv01/variables.tf` (`atomic_hyprland_image_path`, per-VM optional `base`, `vnc_console`, `user_shell`, `package_update`)
- Modify: `libvirt-srv01/main.tf` (second base volume, module wiring)
- Modify: `libvirt-srv01/terraform.tfvars` (`hypr-test` entry)
- Modify: `libvirt-srv01/local.auto.tfvars.example` and README (document the new variable)

**Interfaces:**
- Consumes `output/qcow2/disk.qcow2` from Task 6 (uploaded by the provider from the local path).
- Produces VM `hypr-test` at `192.168.70.14` (verify the address is unused: `grep -r 192.168.70.14 ~/Code/Infrastructure/ansible-homelab-cfg/inventories/lab/` must be empty; pick the next free `.1x` otherwise), user `dwallace` with shell `/usr/bin/elvish`, VNC on srv01 loopback.

All defaults keep the four existing VMs byte-identical in the plan (no graphics, bash shell, package_update true). Check that with `tofu plan` before apply: it must show only additions.

- [ ] **Step 1: Module variables**

Append to `modules/libvirt_vm/variables.tf`:

```hcl
variable "vnc_console" {
  description = "Attach a virtio video device and a VNC console bound to the host loopback (view with virt-viewer over qemu+ssh). Off for headless servers."
  type        = bool
  default     = false
}

variable "user_shell" {
  description = "Login shell cloud-init assigns to the dwallace user"
  type        = string
  default     = "/bin/bash"
}

variable "package_update" {
  description = "cloud-init package_update. Set false for bootc images, where dnf cannot write /usr."
  type        = bool
  default     = true
}
```

- [ ] **Step 2: Module main.tf and template**

In `modules/libvirt_vm/main.tf`, pass the new values into the user-data template:

```hcl
  user_data = templatefile("${path.module}/templates/user-data.yaml.tftpl", {
    name           = var.name
    ssh_public_key = var.ssh_public_key
    user_shell     = var.user_shell
    package_update = var.package_update
  })
```

Inside `devices = { ... }`, after `channels = [...]`, add:

```hcl
    # Optional console. The provider emits no <graphics> by default, so the
    # existing server VMs stay headless unless vnc_console is set.
    graphics = var.vnc_console ? [
      {
        vnc = {
          listen    = "127.0.0.1"
          auto_port = true
        }
      },
    ] : []

    videos = var.vnc_console ? [
      {
        model = {
          type    = "virtio"
          heads   = 1
          primary = "yes"
        }
      },
    ] : []

    # USB tablet gives VNC an absolute pointer (same trick as windows_vm).
    inputs = var.vnc_console ? [
      {
        type = "tablet"
        bus  = "usb"
      },
    ] : []
```

In `templates/user-data.yaml.tftpl` change `shell: /bin/bash` to `shell: ${user_shell}` and `package_update: true` to `package_update: ${package_update}`.

- [ ] **Step 3: Root module**

`libvirt-srv01/variables.tf`, add:

```hcl
variable "atomic_hyprland_image_path" {
  description = "Local path to the atomic-hyprland qcow2 built by `just qcow2`; uploaded to the pool as a base volume"
  type        = string
  default     = ""
}
```

and extend the `vms` object type:

```hcl
variable "vms" {
  description = "Map of VMs to create: name => {ip, vcpu, memory_mib, disk_gib, cpu_mode?, base?, vnc_console?, user_shell?, package_update?}"
  type = map(object({
    ip             = string
    vcpu           = number
    memory_mib     = number
    disk_gib       = number
    cpu_mode       = optional(string, "host-passthrough")
    base           = optional(string, "fedora-cloud")
    vnc_console    = optional(bool, false)
    user_shell     = optional(string, "/bin/bash")
    package_update = optional(bool, true)
  }))
}
```

`libvirt-srv01/main.tf`, add after the existing `libvirt_volume.base`:

```hcl
# atomic-hyprland desktop image, uploaded from the local qcow2 (CoW base for hypr-test).
resource "libvirt_volume" "atomic_hyprland_base" {
  count = var.atomic_hyprland_image_path == "" ? 0 : 1
  name  = "atomic-hyprland-base.qcow2"
  pool  = var.libvirt_pool

  target = {
    format = {
      type = "qcow2"
    }
  }

  create = {
    content = {
      url = var.atomic_hyprland_image_path
    }
  }

  # Re-uploading on every rebuild would replace the base under running
  # clones. Bump by tainting this resource deliberately.
  lifecycle {
    ignore_changes = [create]
  }
}

locals {
  base_volumes = merge(
    { "fedora-cloud" = libvirt_volume.base.path },
    var.atomic_hyprland_image_path == "" ? {} : { "atomic-hyprland" = libvirt_volume.atomic_hyprland_base[0].path },
  )
}
```

and change the module call's `base_volume_id` line plus add the new args:

```hcl
  base_volume_id = local.base_volumes[each.value.base]
  vnc_console    = each.value.vnc_console
  user_shell     = each.value.user_shell
  package_update = each.value.package_update
```

`libvirt-srv01/terraform.tfvars`, add to `vms`:

```hcl
  hypr-test = {
    ip             = "192.168.70.14"
    vcpu           = 4
    memory_mib     = 6144
    disk_gib       = 40
    base           = "atomic-hyprland"
    vnc_console    = true
    user_shell     = "/usr/bin/elvish"
    package_update = false
  }
```

Put the image path in `libvirt-srv01/local.auto.tfvars` (gitignored, machine-specific), and add the line to `local.auto.tfvars.example`:

```hcl
atomic_hyprland_image_path = "/home/dwallace/Code/atomic-hyprland/output/qcow2/disk.qcow2"
```

- [ ] **Step 4: Validate and plan**

```bash
cd ~/Code/Infrastructure/tofu-homelab-cfg/libvirt-srv01
tofu fmt -recursive ..
tofu init
tofu validate
tofu plan -out tfplan
tofu show tfplan | grep -E '^\s*# .* will be' 
```

Expected: exactly two creations (`libvirt_volume.atomic_hyprland_base[0]`, `module.vm["hypr-test"].*` resources) and **zero** changes or replacements on ai01, util01, ai-master, web01. If the plan shows the existing domains being updated because of the new empty `graphics`/`videos`/`inputs` lists, change those three attributes to `null` instead of `[]` in the false branch and re-plan.

- [ ] **Step 5: Apply (confirm with Dan first) and commit**

Tell Dan what the apply creates (one 3 to 5 GB upload to srv01's pool, one VM). Then:

```bash
tofu apply tfplan
tofu output vm_ips
```

Expected: `hypr-test = "192.168.70.14"`.

```bash
cd ..
git switch -c dw/hypr-test-vm
git add modules/libvirt_vm libvirt-srv01/variables.tf libvirt-srv01/main.tf libvirt-srv01/terraform.tfvars libvirt-srv01/local.auto.tfvars.example README.md
git commit -m "feat(tofu): add hypr-test VM from the atomic-hyprland qcow2

Adds optional vnc_console, user_shell and package_update to libvirt_vm,
and a second base volume uploaded from a local qcow2. Existing VMs are
unchanged (verified with tofu plan).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/hypr-test-vm
gh pr create --fill
```

Merge after Dan's review (squash).

---

### Task 8: Verify the VM, write the runbook, open the Obsidian project

**Files:**
- Modify: `~/Code/atomic-hyprland/README.md` (VM runbook, known gaps)
- Obsidian: new project via the `new-project` skill ("Atomic Hyprland")

**Interfaces:** none produced; this task closes Phase 1 with evidence.

- [ ] **Step 1: SSH and bootc checks**

```bash
ssh -o StrictHostKeyChecking=accept-new dwallace@192.168.70.14 'sudo bootc status; echo; getent passwd dwallace; echo; systemctl is-enabled sddm; systemctl get-default; ls ~/.config/hypr'
```

Expected: `bootc status` shows booted image `ghcr.io/danmwallace/atomic-hyprland:44` with the version from the stamp; dwallace's shell is `/usr/bin/elvish`; sddm `enabled`; `graphical.target`; `hyprland.conf hyprlock.conf local.conf scripts xdg-portal-hyprland`.

Also: `ssh dwallace@192.168.70.14 'systemctl --user status atomic-hyprland-dotfiles --no-pager; cat ~/.config/atomic-hyprland/stamp'`. Expected: `inactive (dead)` with "synced" or "up to date" in the log, stamp present. If the user session has not started yet (no login), `loginctl enable-linger dwallace` is not needed; the first graphical login starts it.

- [ ] **Step 2: Tell Hyprland about the virtual display**

The role's `hyprland.conf` only knows Dan's physical monitors. Write the VM override into the file made for that:

```bash
ssh dwallace@192.168.70.14 'cat > ~/.config/hypr/local.conf <<EOF
# VM: virtio-gpu, software rendering
monitor=Virtual-1,preferred,auto,1
cursor {
    no_hardware_cursors = true
}
env = WLR_RENDERER_ALLOW_SOFTWARE,1
EOF'
```

- [ ] **Step 3: Log in on the console**

```bash
virt-viewer -c qemu+ssh://dwallace@10.10.99.4/system hypr-test
```

Expected: SDDM greeter (X11, default theme; the role's `10-theme.conf` names a theme that is not installed, SDDM warns and falls back, which is acceptable for Phase 1 and noted below). Log in as dwallace (set a password first if needed: `ssh dwallace@192.168.70.14 'sudo passwd dwallace'`), session "Hyprland". Expected: Hyprland starts, Waybar appears, `Super+Q` (or the bind in hyprland.conf) opens Alacritty with an elvish prompt. Black wallpaper is expected (`swaybg` points at `~/Pictures/Wallpapers/gray-abstract.jpg`, absent).

If SDDM shows but Hyprland returns to the greeter: `ssh dwallace@192.168.70.14 'cat $XDG_RUNTIME_DIR/hypr/*/hyprland.log | tail -50'` (or `/run/user/1000/hypr/*/hyprland.log`). The usual cause in a VM is no GLES renderer; if the log says so, switch the VM's video to virgl: set `model = { type = "virtio", heads = 1, primary = "yes", accel = { accel3d = "yes" } }` and change `graphics` to `spice = { listen = "none", gl = { enable = "yes" } }`, then view with `virt-viewer --attach`. That is the Hyprland wiki's recommended VM setup and needs srv01 to have a render node.

- [ ] **Step 4: Record verification in the README**

Add to `README.md`:

```markdown
## Phase 1 status (date)

- hypr-test VM on srv01 boots the image, SDDM login, Hyprland session: verified <date>.
- Known gaps (deliberate, later phases): no NVIDIA, no Ollama/LiteLLM, image unsigned
  (policy allows our registry unsigned until Phase 3), SDDM theme in the role's
  10-theme.conf is not installed so SDDM uses its default, default wallpaper missing.

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
```

- [ ] **Step 5: Obsidian project and commit**

Invoke the `new-project` skill with name "Atomic Hyprland", linking the spec and this plan, with tasks for Phases 2 to 4 from the spec. Then:

```bash
cd ~/Code/atomic-hyprland
git add README.md
git commit -m "docs: record Phase 1 VM verification and runbook

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push
```

---

## Self-review notes

- Spec coverage for Phase 1: repo + spec commit (done before this plan), role change (Task 1, 2), Containerfile/build/files (Task 3, 4), push (Task 5), qcow2 + tofu + apply (Task 6, 7), VM verification (Task 8). The spec's `check-kernel-match.sh` runs in Task 3 even though NVIDIA is off, as the spec asks.
- Deviation from spec, stated: the spec listed an `image-builder/config.toml` user for the qcow2. cloud-init (already the pattern for every srv01 VM) does user, SSH key and static IP instead, so no config.toml is needed in Phase 1. The spec's "`files/etc/sddm.conf.d/10-wayland.conf`" is replaced by Fedora's `sddm-x11` greeter package; Wayland greeter needs weston and buys nothing in Phase 1.
- Names used consistently: `hyprland_home_dir`, `hyprland_manage_copr`, `hyprland_manage_services`, `hyprland_file_owner`; `/usr/share/atomic-hyprland/{stamp,skel,managed-files.txt}`; `ATOMIC_HYPRLAND_SHARE`; just recipes `build test lint check-kernel push qcow2`.
