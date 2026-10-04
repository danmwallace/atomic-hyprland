# Phase 2: AI Services and Post-Install Ansible Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Ollama and LiteLLM as Quadlets in the image, move the GUI apps to Flatpaks, and add one control-repo playbook that installs Hermes, configures LiteLLM from vault, pulls Ollama models and installs Flatpaks on `hypr-test`, idempotently.

**Architecture:** The image gains three Quadlet files (`ai.network`, `ollama.container`, `litellm.container`), Claude Code, and loses Firefox/LibreOffice/Thunderbird via a new role variable. LiteLLM stays inert until `playbooks/fedora-hypr-desktop.yml` renders `/etc/litellm/{config.yaml,env}`. The Hermes collection learns to skip its dnf tasks on ostree hosts. Secrets are copied from ai-master's vault into a new `hypr_desktops` group vault without ever being printed.

**Tech Stack:** podman 5.8 Quadlets, bootc image via `just`, Ansible roles (`danmwallace.fedora.hyprland` 1.3.0, `danmwallace.hermes` 1.4.0), ansible-vault, `community.general.flatpak`, LiteLLM `v1.83.14-stable`, Ollama `0.35.1`.

**Spec:** `docs/superpowers/specs/2026-10-04-phase2-ai-services-design.md` (this repo). The Quadlet file contents, variable names and playbook shape there are the authority.

## Global Constraints

- Repos and branches: image `~/Code/atomic-hyprland` on `dw/phase2`; role `~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora` on `dw/desktop-apps` (release **1.3.0**); Hermes collection `~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/hermes` on `dw/ostree-guard` (release **1.4.0**); control repo `~/Code/Infrastructure/ansible-homelab-cfg` on `dw/hypr-desktops` branched from `main` (the checkout currently sits on `dw/claude-md-refresh`; do not touch that branch).
- Pins: `docker.io/ollama/ollama:0.35.1`, `ghcr.io/berriai/litellm:v1.83.14-stable`, `@anthropic-ai/claude-code@2.1.289`.
- Ports: Ollama `127.0.0.1:11434`, LiteLLM `127.0.0.1:4000`, Hermes dashboard `127.0.0.1:9119`, Hermes API `127.0.0.1:8642`. Nothing on a LAN interface.
- Secrets: only in `inventories/lab/group_vars/hypr_desktops/vault.yml`, encrypted with `.vault_pass`; never printed, never in a commit message, never in a log the plan keeps.
- Flatpak list: `org.mozilla.firefox`, `org.libreoffice.LibreOffice`, `org.mozilla.Thunderbird`, `md.obsidian.Obsidian`, `dev.zed.Zed`.
- Ollama models: group default `[llama3.1:8b, qwen2.5-coder:7b, nomic-embed-text]`; `hypr-test` override `[qwen2.5:0.5b, nomic-embed-text]`.
- Control repo conventions (its CLAUDE.md): FQCN only, no plaintext secrets, pin collections with ranges, no roles in the control repo.
- Code style: 2-space YAML, LF, trailing newline, no trailing whitespace; Ansible desired-state task names; `ansible-lint` production profile clean in both collections; `make lint` clean in the control repo.
- Commits: Conventional Commits, imperative, ≤72-char subject, end with the session attribution lines.
- Announce to Dan before the VM reboot (Task 4) and before the first real playbook run (Task 6).

## Review Focus

1. **LiteLLM must not fail-loop on an unconfigured host.** Expectation: a fresh install shows `litellm.service` inactive with "condition failed", not `failed`. Pinned in Task 4 (`systemctl show litellm -p ActiveState,Result` on the VM before the playbook).
2. **A model already present must not be re-pulled.** Expectation: second playbook run pulls nothing. Pinned in Task 6 (second run `changed=0`) and by the name normalisation test in Task 5 (`nomic-embed-text` matches `nomic-embed-text:latest`).
3. **Hermes role on bootc must never call dnf.** Expectation: the role converges on a host where dnf cannot write. Pinned in Task 2's `ostree` molecule scenario (`make` stays absent, `gh-cli.repo` absent).
4. **The vault copy must carry exactly the five keys and nothing else.** Expectation: `ansible-vault view` of the new file lists five names. Pinned in Task 5 Step 2 (names-only check).
5. **The LiteLLM env file must not be world-readable.** Expectation: `/etc/litellm/env` is `0600 root:root`. Pinned in Task 6's acceptance (`stat -c %a`).

---

### Task 1: Role 1.3.0: `hyprland_desktop_apps`

**Files (role repo, branch `dw/desktop-apps`):**
- Modify: `roles/hyprland/defaults/main.yml`, `roles/hyprland/tasks/main.yml`, `roles/hyprland/meta/argument_specs.yml`, `roles/hyprland/README.md`, `CHANGELOG.md`, `galaxy.yml`
- Modify: `roles/hyprland/molecule/skel/converge.yml`, `roles/hyprland/molecule/skel/verify.yml`, `roles/hyprland/molecule/default/verify.yml`

**Interfaces:**
- Produces variable `hyprland_desktop_apps` (list of package names, default `[firefox, libreoffice, thunderbird]`); Task 3's `build/playbook.yml` sets it to `[]`.

- [ ] **Step 1: Write the failing verify assertions**

Append to `molecule/skel/verify.yml` (the `package_facts` task already exists there):

```yaml
    - name: Assert the desktop apps are absent in image mode
      ansible.builtin.assert:
        that:
          - "'firefox' not in ansible_facts.packages"
          - "'libreoffice-core' not in ansible_facts.packages"
          - "'thunderbird' not in ansible_facts.packages"
```

Append to `molecule/default/verify.yml`:

```yaml
    - name: Assert the desktop apps are installed by default
      ansible.builtin.assert:
        that:
          - "'firefox' in ansible_facts.packages"
          - "'thunderbird' in ansible_facts.packages"
```

In `molecule/skel/converge.yml` add `hyprland_desktop_apps: []` under the role's `vars:`.

- [ ] **Step 2: Run the skel scenario to verify it fails**

Run: `cd ~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/fedora && git switch main && git pull && git switch -c dw/desktop-apps && cd roles/hyprland && molecule test -s skel 2>&1 | grep -E 'Executed|fatal|Assertion'`
Expected: converge passes (the variable is unknown and ignored), verify fails at "Assert the desktop apps are absent in image mode" because the role still installs firefox.

- [ ] **Step 3: Implement**

`defaults/main.yml`, append:

```yaml

# Desktop applications installed as RPMs. Image builds set this to [] and ship
# them as Flatpaks instead.
hyprland_desktop_apps:
  - firefox
  - libreoffice
  - thunderbird
```

`tasks/main.yml`: remove `      - firefox`, `      - libreoffice`, `      - thunderbird` from the "Ensure Hyprland and its supporting packages are installed" list, and add right after that task:

```yaml
- name: "Ensure desktop applications are installed"
  ansible.builtin.dnf:
    name: "{{ hyprland_desktop_apps }}"
    state: present
  become: true
  when: hyprland_desktop_apps | length > 0
```

`meta/argument_specs.yml`, append under `options:`:

```yaml
      hyprland_desktop_apps:
        description:
          - Desktop applications installed as RPMs. Set to an empty list on image
            builds that ship them as Flatpaks.
        type: list
        elements: str
        required: false
        default: [firefox, libreoffice, thunderbird]
```

`roles/hyprland/README.md`: add a table row `| hyprland_desktop_apps | list | no | [firefox, libreoffice, thunderbird] | RPM desktop apps; [] on image builds (Flatpaks instead). |`. `CHANGELOG.md`: insert above `## [1.2.0]`:

```markdown
## [1.3.0] - 2026-10-04

### Added

- `hyprland_desktop_apps` (default `firefox`, `libreoffice`, `thunderbird`) so
  image builds can set it to `[]` and ship those apps as Flatpaks.
```

`galaxy.yml`: `version: 1.3.0`.

- [ ] **Step 4: Run both scenarios serially, then lint**

Run: `molecule test -s skel 2>&1 | grep -E 'Executed|failed='; molecule test -s default 2>&1 | grep -E 'Executed|failed='; cd ../.. && ansible-lint`
Expected: skel and default all phases successful with idempotence `changed=0`; lint `Passed`. Never run the two scenarios concurrently (molecule's prerun races on `~/.ansible/collections`).

- [ ] **Step 5: Commit, PR, merge, tag**

```bash
git add roles/hyprland CHANGELOG.md galaxy.yml
git commit -m "feat(hyprland): make the RPM desktop apps a variable; release v1.3.0

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/desktop-apps
gh pr create --title "feat(hyprland): hyprland_desktop_apps variable (v1.3.0)" --body "..."
# wait for CI, then
gh pr merge --squash --delete-branch && git switch main && git pull
git tag -a v1.3.0 -m "v1.3.0" && git push origin v1.3.0
```

Expected: Release workflow publishes 1.3.0 (`gh run list --workflow Release --limit 1`).

---

### Task 2: Hermes 1.4.0: ostree guard

**Files (Hermes repo, branch `dw/ostree-guard`):**
- Create: `roles/hermes_native/tasks/ostree.yml`
- Modify: `roles/hermes_native/tasks/main.yml`, `packages.yml`, `gh.yml`
- Create: `roles/claude_code/tasks/ostree.yml`; Modify: `roles/claude_code/tasks/main.yml`, `install.yml`
- Create: `roles/hermes_native/molecule/ostree/{molecule.yml,create.yml,destroy.yml,converge.yml,verify.yml,inventory/hosts.yml}`
- Modify: `roles/hermes_native/README.md`, `CHANGELOG.md`, `galaxy.yml`

**Interfaces:**
- Produces fact `hermes_native_ostree_booted` (stat result) and `claude_code_ostree_booted`; dnf and gh-repo tasks carry `when: not <fact>.stat.exists`.

- [ ] **Step 1: Write the failing molecule scenario**

`molecule/ostree/molecule.yml`:

```yaml
---
dependency:
  name: galaxy
ansible:
  executor:
    backend: ansible-playbook
    args:
      ansible_playbook:
        - --inventory=${MOLECULE_SCENARIO_DIRECTORY}/inventory/hosts.yml
scenario:
  test_sequence:
    - dependency
    - destroy
    - create
    - converge
    - verify
    - destroy
```

`create.yml`:

```yaml
---
- name: Create molecule instance
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Start hermes-ostree container
      containers.podman.podman_container:
        name: hermes-ostree
        image: registry.fedoraproject.org/fedora:44
        state: started
        command: sleep infinity
```

`destroy.yml`:

```yaml
---
- name: Destroy molecule instance
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Remove hermes-ostree container
      containers.podman.podman_container:
        name: hermes-ostree
        state: absent
```

`inventory/hosts.yml`:

```yaml
---
molecule:
  hosts:
    hermes-ostree:
      ansible_connection: containers.podman.podman
```

`converge.yml` (only the package-touching task files, on a host that claims to be ostree):

```yaml
---
- name: Converge the ostree guard
  hosts: molecule
  gather_facts: false
  tasks:
    - name: Ensure python3 exists for Ansible modules
      ansible.builtin.raw: dnf -y install python3
      changed_when: false

    - name: Gather facts
      ansible.builtin.setup:

    - name: Pretend to be a bootc host
      ansible.builtin.file:
        path: /run/ostree-booted
        state: touch
        mode: "0644"

    - name: Run the guarded package tasks of hermes_native
      ansible.builtin.include_role:
        name: danmwallace.hermes.hermes_native
        tasks_from: "{{ item }}"
      loop:
        - ostree.yml
        - packages.yml
        - gh.yml
```

`verify.yml`:

```yaml
---
- name: Verify the guard skipped every dnf and repo task
  hosts: molecule
  gather_facts: false
  tasks:
    - name: Gather installed packages
      ansible.builtin.package_facts:
        manager: rpm

    - name: Stat the gh repo file
      ansible.builtin.stat:
        path: /etc/yum.repos.d/gh-cli.repo
      register: hermes_gh_repo

    - name: Assert nothing was installed or dropped into /etc/yum.repos.d
      ansible.builtin.assert:
        that:
          - "'make' not in ansible_facts.packages"
          - "'ripgrep' not in ansible_facts.packages"
          - "'gh' not in ansible_facts.packages"
          - not hermes_gh_repo.stat.exists
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/Code/Infrastructure/dev-collections/ansible_collections/danmwallace/hermes && git switch main && git pull && git switch -c dw/ostree-guard && cd roles/hermes_native && molecule test -s ostree 2>&1 | grep -E 'Executed|fatal|Assertion|ostree.yml'`
Expected: converge fails on `tasks_from: ostree.yml` (file does not exist). That is the RED; if molecule instead reports it skipped the missing file, the verify assertion fails because `packages.yml` installed `make`.

- [ ] **Step 3: Implement the guard**

`roles/hermes_native/tasks/ostree.yml`:

```yaml
# SPDX-License-Identifier: MIT
---
# bootc / rpm-ostree hosts have a read-only /usr: the image must already carry
# every package this role would dnf-install. Detect once; dnf tasks check it.
- name: Detect an ostree (bootc) host
  ansible.builtin.stat:
    path: /run/ostree-booted
  register: hermes_native_ostree_booted
```

`roles/hermes_native/tasks/main.yml`: insert as the first task (before the secret assertions):

```yaml
- name: Detect ostree hosts
  ansible.builtin.import_tasks: ostree.yml
```

`packages.yml`: add `  when: not hermes_native_ostree_booted.stat.exists` to the dnf task. `gh.yml`: add the same `when:` to both tasks.

`roles/claude_code/tasks/ostree.yml`:

```yaml
# SPDX-License-Identifier: MIT
---
- name: Detect an ostree (bootc) host
  ansible.builtin.stat:
    path: /run/ostree-booted
  register: claude_code_ostree_booted
```

`roles/claude_code/tasks/main.yml`: import `ostree.yml` first. `install.yml`: `when: not claude_code_ostree_booted.stat.exists` on the dnf task only.

`roles/hermes_native/README.md` Requirements: add "- On bootc/rpm-ostree hosts (`/run/ostree-booted` present) the role skips its dnf tasks; the image must already provide git, make, jq, yq, ripgrep, python3, python3-pip, curl, nodejs, npm and gh." `CHANGELOG.md`: insert above `## [1.3.3]`:

```markdown
## [1.4.0] - 2026-10-04

### Added

- `hermes_native` and `claude_code` skip their dnf and yum-repo tasks on
  bootc/rpm-ostree hosts (`/run/ostree-booted`), where `/usr` is read-only and
  the image carries the packages. New molecule scenario `ostree` for
  `hermes_native` proves nothing is installed in that mode.
```

`galaxy.yml`: `version: 1.4.0`.

- [ ] **Step 4: Run the scenario and lint**

Run: `molecule test -s ostree 2>&1 | grep -E 'Executed|failed='; cd ../.. && ansible-lint`
Expected: converge and verify successful; lint `Passed`. (Existing `hermes` and `hermes_gateway` scenarios are unaffected; run `molecule test -s default` in `roles/hermes` only if lint flags something there.)

- [ ] **Step 5: Commit, PR, merge, tag**

```bash
git add roles/hermes_native roles/claude_code CHANGELOG.md galaxy.yml
git commit -m "feat: skip dnf tasks on bootc hosts in hermes_native and claude_code; release v1.4.0

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/ostree-guard
gh pr create --title "feat: ostree guard for hermes_native and claude_code (v1.4.0)" --body "..."
# wait for CI, then
gh pr merge --squash --delete-branch && git switch main && git pull
git tag -a v1.4.0 -m "v1.4.0" && git push origin v1.4.0
```

Expected: Release workflow succeeds on Galaxy.

---

### Task 3: Image: Quadlets, Claude Code, Flatpak-only apps

**Files (`~/Code/atomic-hyprland`, branch `dw/phase2`):**
- Create: `files/usr/share/containers/systemd/ai.network`, `ollama.container`, `litellm.container`
- Modify: `build/10-packages.sh`, `build/playbook.yml`, `build/requirements.yml`, `Containerfile`, `justfile` (pass `CLAUDE_CODE_VERSION`), `tests/image-smoke.sh`, `README.md`

**Interfaces:**
- Produces generated units `ai-network.service`, `ollama.service` (active on first boot), `litellm.service` (inert until `/etc/litellm/config.yaml` and `/etc/litellm/env` exist), `/usr/bin/claude` 2.1.289. Task 5's templates target exactly `/etc/litellm/config.yaml` (mounted at `/app/config.yaml`) and `/etc/litellm/env`.

- [ ] **Step 1: Write the failing smoke checks**

Append to `tests/image-smoke.sh` before `exit "$fail"`:

```bash
# Phase 2: AI service Quadlets, Claude Code, GUI apps as Flatpaks
check test -f /usr/share/containers/systemd/ai.network
check test -f /usr/share/containers/systemd/ollama.container
check test -f /usr/share/containers/systemd/litellm.container
gen_out="$(/usr/lib/systemd/system-generators/podman-system-generator --dryrun 2>&1)"
check bash -c "grep -q 'ollama.service' <<< '$gen_out'"
check bash -c "grep -q 'litellm.service' <<< '$gen_out'"
check bash -c "grep -q 'ai-network.service' <<< '$gen_out'"
check bash -c "! grep -qi 'error' <<< '$gen_out'"
check bash -c 'claude --version | grep -q "^2\.1\.289"'
check bash -c '! rpm -q firefox'
check bash -c '! rpm -q libreoffice-core'
check bash -c '! rpm -q thunderbird'
```

Replace the `$gen_out` inline-quoting with the existing `expect_out` helper to be safe: set `out="$gen_out"` and use `expect_out "generator renders ollama.service" present 'ollama.service'` etc., and `expect_out "generator reports no errors" absent '[Ee]rror'`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/Code/atomic-hyprland && podman run --rm -v ./tests:/tests:ro,Z ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/image-smoke.sh 2>&1 | grep FAIL`
Expected: FAIL lines for the three Quadlet files, the three generator units, `claude --version`, and the three `! rpm -q` checks (the apps are still RPMs in the current image).

- [ ] **Step 3: Quadlet files**

`files/usr/share/containers/systemd/ai.network`:

```ini
[Network]
NetworkName=ai
```

`files/usr/share/containers/systemd/ollama.container`:

```ini
[Unit]
Description=Ollama local model server
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/ollama/ollama:0.35.1
ContainerName=ollama
Network=ai.network
Volume=/var/lib/ollama:/root/.ollama:Z
PublishPort=127.0.0.1:11434:11434

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
```

`files/usr/share/containers/systemd/litellm.container`:

```ini
[Unit]
Description=LiteLLM gateway (Anthropic + local Ollama)
After=network-online.target ollama.service
Wants=network-online.target
# Inert until the post-install playbook renders the config and env file.
ConditionPathExists=/etc/litellm/config.yaml
ConditionPathExists=/etc/litellm/env

[Container]
Image=ghcr.io/berriai/litellm:v1.83.14-stable
ContainerName=litellm
Network=ai.network
Volume=/etc/litellm/config.yaml:/app/config.yaml:ro,Z
EnvironmentFile=/etc/litellm/env
Exec=--config /app/config.yaml --port 4000
PublishPort=127.0.0.1:4000:4000

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Build changes**

`Containerfile`: add `ARG CLAUDE_CODE_VERSION=2.1.289` after `ARG IMAGE_VERSION=dev`, and change the packages line to `RUN /tmp/build/10-packages.sh "${CLAUDE_CODE_VERSION}"`. `build/10-packages.sh`: accept `claude_code_version="${1:?claude code version}"` at the top and append after the ansible-core install:

```bash
# Claude Code for every user (Dan and the hermes agent). npm global writes
# /usr/lib/node_modules, which only works at build time on a bootc image.
npm install -g "@anthropic-ai/claude-code@${claude_code_version}"
```

`build/playbook.yml`: add `        hyprland_desktop_apps: []` with the comment `# Firefox, LibreOffice, Thunderbird are Flatpaks on the image (see the control repo's desktop_flatpaks).` `build/requirements.yml`: `version: v1.3.0`. `justfile`: no change needed (the ARG default is the pin; bump it in the Containerfile).

- [ ] **Step 5: Build, test, push**

Run: `just check-kernel && just build 2>&1 | tail -3 && just test && just push && skopeo inspect --no-creds docker://ghcr.io/danmwallace/atomic-hyprland:44 | jq -r '.Labels["org.opencontainers.image.version"]'`
Expected: lint passes inside the build; `just test` all `ok` (both suites); push succeeds; version label matches `git rev-parse --short HEAD` of the committed tree (commit first: Step 6, then build, so the label is clean; or build, commit, rebuild the last layers and push, as the Lua port did).

- [ ] **Step 6: README and commit**

`README.md`, add under "Phase 1 status":

```markdown
## AI services (Phase 2)

The image ships `ollama.service` (starts on first boot, models under
`/var/lib/ollama`) and `litellm.service`, which stays inactive until
`playbooks/fedora-hypr-desktop.yml` in ansible-homelab-cfg renders
`/etc/litellm/config.yaml` and `/etc/litellm/env`. Both bind to loopback only.
Claude Code is in the image for every user. Firefox, LibreOffice and
Thunderbird are Flatpaks installed by the same playbook.
```

```bash
git add files build Containerfile tests/image-smoke.sh README.md
git commit -m "feat: Ollama and LiteLLM Quadlets, Claude Code in the image, GUI apps as Flatpaks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/phase2
```

---

### Task 4: VM upgrade and pre-playbook state

**Files:** none.

- [ ] **Step 1: Announce, upgrade, reboot**

Tell Dan the VM reboots. Then:

```bash
ssh dwallace@192.168.70.14 bash -c "'sudo bootc upgrade 2>&1 | tail -3; sudo systemctl reboot'"
until ssh -o ConnectTimeout=5 -o BatchMode=yes dwallace@192.168.70.14 true 2>/dev/null; do sleep 5; done
```

- [ ] **Step 2: Verify the image-only state (Review Focus 1)**

```bash
ssh dwallace@192.168.70.14 bash -s <<'EOF'
sudo bootc status --format json | jq -r '.status.booted.image.version'
systemctl is-active ollama; systemctl show litellm -p ActiveState -p Result -p ConditionResult
curl -s 127.0.0.1:11434/api/tags
claude --version
rpm -q firefox || echo "firefox not an RPM (expected)"
EOF
```
Expected: new version; `ollama` `active` (allow a minute for the image pull on first start; re-check); `litellm` `ActiveState=inactive`, `Result=success`, `ConditionResult=no`; `/api/tags` returns `{"models":[]}`; `claude --version` is 2.1.289; firefox absent.

---

### Task 5: Control repo: group, variables, vault, playbook

**Files (`~/Code/Infrastructure/ansible-homelab-cfg`, branch `dw/hypr-desktops` from `main`):**
- Modify: `inventories/lab/inventory`, `requirements.yml`, `CLAUDE.md` (playbook list)
- Create: `inventories/lab/group_vars/hypr_desktops/{connection,hermes,litellm,ollama,flatpaks,vault}.yml`
- Create: `inventories/lab/host_vars/hypr-test/ollama.yml`
- Create: `playbooks/fedora-hypr-desktop.yml`, `playbooks/tasks/hypr-desktop/{litellm,ollama,flatpaks}.yml`, `playbooks/templates/hypr-desktop/{litellm-config.yaml.j2,litellm-env.j2}`

**Interfaces:**
- Consumes the Quadlet paths from Task 3 and the roles from Tasks 1 and 2.
- Produces the playbook Task 6 runs.

- [ ] **Step 1: Branch and inventory**

```bash
cd ~/Code/Infrastructure/ansible-homelab-cfg && git switch main && git pull && git switch -c dw/hypr-desktops
```

In `inventories/lab/inventory`, add under `children:` after `workstations`:

```yaml
    hypr_desktops:
      hosts:
        hypr-test:
          ansible_host: 192.168.70.14
```

- [ ] **Step 2: Vault copy (no values printed) and its names-only test**

```bash
mkdir -p inventories/lab/group_vars/hypr_desktops
v=.venv/bin/ansible-vault
{ $v view inventories/lab/host_vars/ai-master/vault.yml \
    | grep -E '^vault_(hermes_native_anthropic_api_key|hermes_native_gh_token|hermes_dashboard_basic_auth_password|hermes_api_server_key):'; \
  printf 'vault_litellm_master_key: "sk-%s"\n' "$(openssl rand -hex 32)"; } \
  | $v encrypt --output inventories/lab/group_vars/hypr_desktops/vault.yml
$v view inventories/lab/group_vars/hypr_desktops/vault.yml | grep -oE '^vault_[a-z0-9_]+' | sort
```
Expected: exactly five names: `vault_hermes_api_server_key`, `vault_hermes_dashboard_basic_auth_password`, `vault_hermes_native_anthropic_api_key`, `vault_hermes_native_gh_token`, `vault_litellm_master_key`. If a name is missing, the grep pattern missed a key in ai-master's file; fix the pattern and re-run (the pipe never shows values).

- [ ] **Step 3: Variables**

`group_vars/hypr_desktops/connection.yml`:

```yaml
---
# atomic-hyprland hosts are provisioned with the dwallace login (cloud-init on
# the VM, the existing user on the Alienware).
ansible_user: dwallace
```

`group_vars/hypr_desktops/hermes.yml`:

```yaml
---
# Vault vars required (group_vars/hypr_desktops/vault.yml):
#   vault_hermes_native_anthropic_api_key, vault_hermes_native_gh_token,
#   vault_hermes_dashboard_basic_auth_password, vault_hermes_api_server_key
hermes_native_user: hermes
hermes_native_workspace_dir: /home/hermes/workspace
hermes_native_git_user_name: "Hermes"
hermes_native_git_user_email: "hermes@wallace.boston"
hermes_native_anthropic_api_key: "{{ vault_hermes_native_anthropic_api_key }}"
hermes_native_api_server_key: "{{ vault_hermes_api_server_key }}"
hermes_native_api_server_model_name: hermes-desktop
hermes_native_dashboard_password: "{{ vault_hermes_dashboard_basic_auth_password }}"
hermes_native_gh_token: "{{ vault_hermes_native_gh_token }}"
# Desktop: loopback only, no Traefik, no Discord.
hermes_native_dashboard_host: "127.0.0.1"
hermes_native_api_server_host: "127.0.0.1"
hermes_native_dashboard_traefik_enabled: false
hermes_native_nopasswd_sudo: true
hermes_native_sudo_commands:
  - /usr/bin/systemctl
  - /usr/bin/podman
  - /usr/bin/journalctl
hermes_native_approvals_mode: smart
hermes_native_approvals_cron_mode: allow
```

`group_vars/hypr_desktops/litellm.yml`:

```yaml
---
# Vault var required: vault_litellm_master_key
litellm_master_key: "{{ vault_litellm_master_key }}"
# Hosted models. Ollama entries are generated from ollama_models.
litellm_models:
  - name: claude-sonnet
    model: anthropic/claude-sonnet-4-6
  - name: claude-opus
    model: anthropic/claude-opus-4-1
```

`group_vars/hypr_desktops/ollama.yml`:

```yaml
---
# Pulled by playbooks/tasks/hypr-desktop/ollama.yml; override per host.
ollama_models:
  - llama3.1:8b
  - qwen2.5-coder:7b
  - nomic-embed-text
```

`group_vars/hypr_desktops/flatpaks.yml`:

```yaml
---
desktop_flatpaks:
  - org.mozilla.firefox
  - org.libreoffice.LibreOffice
  - org.mozilla.Thunderbird
  - md.obsidian.Obsidian
  - dev.zed.Zed
```

`host_vars/hypr-test/ollama.yml`:

```yaml
---
# CPU-only VM with 6 GiB: keep the pulls small.
ollama_models:
  - qwen2.5:0.5b
  - nomic-embed-text
```

- [ ] **Step 4: Templates and task files**

`playbooks/templates/hypr-desktop/litellm-config.yaml.j2`:

```yaml
# {{ ansible_managed }}
model_list:
{% for m in litellm_models %}
  - model_name: {{ m.name }}
    litellm_params:
      model: {{ m.model }}
{% if m.model.startswith('anthropic/') %}
      api_key: os.environ/ANTHROPIC_API_KEY
{% endif %}
{% endfor %}
{% for m in ollama_models %}
  - model_name: {{ m.split(':')[0] }}
    litellm_params:
      model: ollama/{{ m }}
      api_base: http://ollama:11434
{% endfor %}

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

`playbooks/templates/hypr-desktop/litellm-env.j2`:

```
# {{ ansible_managed }}
ANTHROPIC_API_KEY={{ vault_hermes_native_anthropic_api_key }}
LITELLM_MASTER_KEY={{ litellm_master_key }}
```

`playbooks/tasks/hypr-desktop/litellm.yml`:

```yaml
---
- name: Ensure the LiteLLM config directory exists
  ansible.builtin.file:
    path: /etc/litellm
    state: directory
    owner: root
    group: root
    mode: "0750"

- name: Ensure the LiteLLM config is rendered
  ansible.builtin.template:
    src: ../templates/hypr-desktop/litellm-config.yaml.j2
    dest: /etc/litellm/config.yaml
    owner: root
    group: root
    mode: "0644"
  notify: Restart litellm

- name: Ensure the LiteLLM env file is rendered
  ansible.builtin.template:
    src: ../templates/hypr-desktop/litellm-env.j2
    dest: /etc/litellm/env
    owner: root
    group: root
    mode: "0600"
  no_log: true
  notify: Restart litellm

- name: Ensure systemd has re-evaluated the Quadlet units
  ansible.builtin.systemd_service:
    daemon_reload: true

- name: Ensure LiteLLM is running
  ansible.builtin.systemd_service:
    name: litellm
    state: started
```

`playbooks/tasks/hypr-desktop/ollama.yml`:

```yaml
---
- name: Ensure Ollama is running
  ansible.builtin.systemd_service:
    name: ollama
    state: started

- name: Wait for the Ollama API
  ansible.builtin.wait_for:
    host: 127.0.0.1
    port: 11434
    timeout: 300

- name: Read the models Ollama already has
  ansible.builtin.uri:
    url: http://127.0.0.1:11434/api/tags
    return_content: true
  register: ollama_tags

- name: Normalise present model names (Ollama reports name:tag; a bare name means :latest)
  ansible.builtin.set_fact:
    ollama_present: "{{ ollama_tags.json.models | default([]) | map(attribute='name') | list }}"
    ollama_wanted: "{{ ollama_models | map('regex_replace', '^([^:]+)$', '\\1:latest') | list }}"

- name: Ensure each wanted model is pulled
  ansible.builtin.command: podman exec ollama ollama pull {{ item }}
  loop: "{{ ollama_wanted }}"
  when: item not in ollama_present
  changed_when: true
```

`playbooks/tasks/hypr-desktop/flatpaks.yml`:

```yaml
---
- name: Ensure desktop Flatpaks are installed from Flathub
  community.general.flatpak:
    name: "{{ desktop_flatpaks }}"
    remote: flathub
    method: system
    state: present
```

`playbooks/fedora-hypr-desktop.yml`:

```yaml
---
- name: Configure atomic-hyprland desktops — AI services and Hermes
  hosts: hypr_desktops
  become: true
  pre_tasks:
    - name: Detect a bootc host
      ansible.builtin.stat:
        path: /run/ostree-booted
      register: hypr_ostree

    - name: Assert this is an atomic-hyprland (bootc) host
      ansible.builtin.assert:
        that: hypr_ostree.stat.exists
        fail_msg: "fedora-hypr-desktop.yml targets atomic-hyprland (bootc) hosts only; the image carries the packages"
  roles:
    - role: danmwallace.hermes.hermes_native
      tags: [hermes, agent]
  tasks:
    - name: Configure LiteLLM
      ansible.builtin.import_tasks: tasks/hypr-desktop/litellm.yml
      tags: [litellm, ai]

    - name: Ensure Ollama models are present
      ansible.builtin.import_tasks: tasks/hypr-desktop/ollama.yml
      tags: [ollama, ai]

    - name: Ensure desktop Flatpaks are installed
      ansible.builtin.import_tasks: tasks/hypr-desktop/flatpaks.yml
      tags: [flatpaks, apps]
  handlers:
    - name: Restart litellm
      ansible.builtin.systemd_service:
        name: litellm
        state: restarted
```

`requirements.yml`: `danmwallace.fedora` to `">=1.3.0,<2.0.0"`, `danmwallace.hermes` to `">=1.4.0,<2.0.0"`. `CLAUDE.md`: add `fedora-hypr-desktop.yml` to the playbook list with one line. Then `make requirements` (or `make setup`) so the venv has the new collection versions.

- [ ] **Step 5: Lint and check mode**

Run: `make lint 2>&1 | tail -5; make check PLAYBOOK=playbooks/fedora-hypr-desktop.yml 2>&1 | tail -25`
Expected: lint clean for the new playbook; check mode shows the Hermes role's intended changes, the two LiteLLM templates as "changed" with a diff, model pulls skipped (check mode cannot exec), Flatpaks "changed". No failures. The `uri` task against Ollama runs even in check mode (it is read-only).

- [ ] **Step 6: Commit and push the branch**

```bash
git add inventories/lab/inventory inventories/lab/group_vars/hypr_desktops inventories/lab/host_vars/hypr-test playbooks/fedora-hypr-desktop.yml playbooks/tasks/hypr-desktop playbooks/templates/hypr-desktop requirements.yml CLAUDE.md
git commit -m "feat: hypr_desktops group and fedora-hypr-desktop playbook (Hermes, LiteLLM, Ollama, Flatpaks)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
git push -u origin dw/hypr-desktops
```

The vault file is encrypted and committed like every other vault in the repo.

---

### Task 6: Run the playbook, prove idempotence, acceptance

**Files:** none new (README notes in Task 7).

- [ ] **Step 1: Announce and run**

Tell Dan the first real run installs Hermes (clones upstream, builds a venv, takes a few minutes), pulls two small models (~500 MB) and installs five Flatpaks (~1 GB). Then:

```bash
make run PLAYBOOK=playbooks/fedora-hypr-desktop.yml 2>&1 | tail -15
```
Expected: `failed=0`, `changed>0`.

- [ ] **Step 2: Second run**

Run: `make run PLAYBOOK=playbooks/fedora-hypr-desktop.yml 2>&1 | grep -E 'changed=|failed='`
Expected: `changed=0 ... failed=0`. If a task reports changed, it is a bug in that task's idempotence (most likely the Hermes role's uv sync or the model name normalisation); fix the cause, not the symptom.

- [ ] **Step 3: Acceptance over SSH**

```bash
key=$(.venv/bin/ansible-vault view inventories/lab/group_vars/hypr_desktops/vault.yml | awk -F'"' '/vault_litellm_master_key/{print $2}')
ssh dwallace@192.168.70.14 bash -s -- "$key" <<'EOF'
key=$1
systemctl is-active ollama litellm hermes-agent hermes-dashboard
stat -c '%a %U:%G' /etc/litellm/env
curl -s 127.0.0.1:11434/api/tags | jq -r '.models[].name'
curl -s -H "Authorization: Bearer $key" 127.0.0.1:4000/v1/models | jq -r '.data[].id'
curl -s -H "Authorization: Bearer $key" -H 'Content-Type: application/json' 127.0.0.1:4000/v1/chat/completions \
  -d '{"model":"qwen2.5","messages":[{"role":"user","content":"Say hello in five words."}],"max_tokens":30}' | jq -r '.choices[0].message.content'
curl -s -o /dev/null -w '%{http_code}\n' 127.0.0.1:9119
flatpak list --app --columns=application
claude --version
EOF
```
Expected: four `active`; `600 root:root`; `qwen2.5:0.5b` and `nomic-embed-text:latest`; model ids `claude-sonnet`, `claude-opus`, `qwen2.5`, `nomic-embed-text`; a short greeting from the local model (CPU, may take 10 to 30 s); `401` or `200` from the dashboard (auth challenge counts as answering); the five Flatpak ids; `2.1.289`. The key is held in a shell variable and passed as an argument, not echoed.

- [ ] **Step 4: Dan's check**

Ask Dan to open Wofi on the VM and launch Firefox (now a Flatpak). Record the result in the vault task.

---

### Task 7: Docs, PR for the control repo, vault project

**Files:** `~/Code/atomic-hyprland/README.md` (status line), control repo PR, Obsidian tasks.

- [ ] **Step 1: README status**

Append to the "AI services (Phase 2)" section in the image README: "Verified on hypr-test <date>: Ollama (CPU), LiteLLM with Anthropic + local models, Hermes dashboard on 9119, five Flatpaks." Commit and push on `dw/phase2`.

- [ ] **Step 2: Control repo PR**

```bash
cd ~/Code/Infrastructure/ansible-homelab-cfg && gh pr create --title "feat: hypr_desktops group and fedora-hypr-desktop playbook" --body "..."
```
Dan merges after review (the repo has no CI gate; `make lint` was run in Task 5).

- [ ] **Step 3: Vault**

Mark "Phase 2 Quadlets and Post-Install Ansible" Done in `Projects/Atomic Hyprland/Tasks/`; update "Current Focus" in `Project Overview.md` to point at Phase 3; add a Low task "Clean up orphaned group_vars/desktop in ansible-homelab-cfg".

---

## Self-review notes

- Spec coverage: decisions (T1 apps variable, T3 Quadlets and Claude Code, T5 Hermes local-only and vault copy, T5 Flatpak list in group vars), image section (T3), role 1.3.0 (T1), Hermes 1.4.0 (T2), control repo inventory/vars/playbook/templates/task files (T5), testing and rollout (T4, T6), docs (T7). Rollback needs no task.
- Names consistent: `hyprland_desktop_apps`; `hermes_native_ostree_booted` / `claude_code_ostree_booted`; `litellm_models`, `litellm_master_key`, `ollama_models`, `desktop_flatpaks`; `/etc/litellm/{config.yaml,env}`; units `ollama`, `litellm`, `ai-network`; handler `Restart litellm`.
- Review Focus pinned: 1 → T4 Step 2; 2 → T6 Step 2 and T5's `ollama_wanted` normalisation; 3 → T2 scenario; 4 → T5 Step 2; 5 → T6 Step 3 `stat`.
