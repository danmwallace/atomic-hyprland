# Phase 2: AI services and post-install Ansible: design

Approved in conversation 2026-10-04. Implements the "Phase 2" section of
`2026-10-03-atomic-hyprland-design.md` with the decisions below. The layer rule
from the main spec still binds: the image owns everything that is the same for
every install; Ansible owns secrets and per-machine state; `/var` owns data.

## Decisions

- **GUI apps become Flatpaks.** Firefox, LibreOffice and Thunderbird leave the
  image. The role gains `hyprland_desktop_apps` (default keeps today's RPM list
  for non-image hosts); the image build sets it to `[]`.
- **Quadlets in the image, configuration from Ansible.** `ollama.container`,
  `litellm.container` and `ai.network` ship in the image. Ollama needs no
  configuration. LiteLLM's unit is gated by `ConditionPathExists=/etc/litellm/config.yaml`
  so it is inert until the playbook renders its config and env file.
- **Claude Code in the image**, pinned npm global install at build time, for
  every user including `hermes`. The `claude_code` role is not used on desktops
  (its global npm install cannot write a read-only `/usr`).
- **Hermes is a local agent only**: `hermes_native` with dashboard and API on
  loopback, no Traefik, no Discord, no extra profiles. It talks to Anthropic
  directly (the role has no base-URL option); LiteLLM serves editors and tools.
- **Secrets are copied from ai-master's vault** into the new group vault
  without being printed, plus a freshly generated LiteLLM master key.
- **Flatpak list lives in group vars**, not in the image (Ansible installs them;
  per-host overrides belong with the inventory). Flathub is already configured
  by the base image's first-boot service.
- **Control-repo group is `hypr_desktops`.** The orphaned `group_vars/desktop`
  directory (no matching inventory group) is left alone; cleanup is a separate
  task.

## Facts verified 2026-10-04

| Fact | How |
|---|---|
| Image has `flathub` remote (system) via ublue's `flatpak-add-fedora-repos.service`; podman 5.8.7; no Quadlets yet | `podman run` in the image |
| Ollama latest tagged release `0.35.1`; LiteLLM latest stable tag `v1.83.14-stable` | `skopeo list-tags` |
| `@anthropic-ai/claude-code` latest `2.1.289` | `npm view` |
| Flathub has `org.mozilla.firefox`, `org.libreoffice.LibreOffice`, `org.mozilla.Thunderbird`, `md.obsidian.Obsidian`, `dev.zed.Zed` | Flathub API 200 |
| `hermes_native` writes only to `/etc`, `/home/hermes`, `/etc/systemd/system`, `/etc/sudoers.d`; its `/usr` writes are the dnf tasks in `packages.yml`, `gh.yml` plus the gh repo file | role tasks read |
| Image already carries every package `hermes_native` dnf-installs (git make jq yq ripgrep python3 python3-pip curl nodejs npm gh) | `build/packages.txt` |
| `claude_code` role: dnf nodejs/npm then `community.general.npm global: true` | role tasks read |
| Control repo: inventory at `inventories/lab/inventory`; VMs use `ansible_user: dwallace`; vault password file `.vault_pass` present; Hermes secrets live in `host_vars/ai-master/vault.yml` under `vault_hermes_native_anthropic_api_key`, `vault_hermes_native_gh_token`, `vault_hermes_dashboard_basic_auth_password`, `vault_hermes_api_server_key` | files read, vault names listed without values |
| hypr-test VM: 4 vCPU, 6 GiB, no GPU, 192.168.70.14 | tofu |

## Image

### Quadlets (`files/usr/share/containers/systemd/`)

`ai.network`:

```ini
[Network]
NetworkName=ai
```

`ollama.container`:

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

`litellm.container`:

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

Images are not pulled at build time; podman pulls them on first start. The
Phase 4 GPU attachment is a drop-in `ollama.container.d/nvidia.conf`.

### Build changes

- `build/10-packages.sh`: after the package install, `npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"` with `ARG CLAUDE_CODE_VERSION=2.1.289` passed from the Containerfile.
- `build/playbook.yml`: `hyprland_desktop_apps: []`.
- `build/requirements.yml`: role tag `v1.3.0`.
- `build/40-finalize.sh`: `install -d -m 0755 /var/lib/ollama` is **not** done (bootc keeps `/var` from the image only at first install; the Quadlet's `Volume=` creates the directory on first start).

### Smoke test additions (`tests/image-smoke.sh`)

- the three Quadlet files exist;
- `/usr/lib/systemd/system-generators/podman-system-generator --dryrun` exits 0 and its output contains `ollama.service`, `litellm.service`, `ai-network.service`;
- `claude --version` prints `2.1.289`;
- `! rpm -q firefox`, `! rpm -q libreoffice-core`, `! rpm -q thunderbird`.

## Role `danmwallace.fedora.hyprland` 1.3.0 (bounded)

- New variable `hyprland_desktop_apps`, type list, default `[firefox, libreoffice, thunderbird]`.
- The package task's list no longer contains those three; a second dnf task installs `hyprland_desktop_apps` when the list is non-empty.
- Molecule: skel scenario converges with `hyprland_desktop_apps: []` and verify asserts the three are absent; default scenario keeps the default and asserts `firefox` present.
- argument_specs, README table, CHANGELOG (Added), galaxy 1.3.0.

## Hermes collection 1.4.0 (bounded)

- `hermes_native/tasks/main.yml`: first task stats `/run/ostree-booted` into `hermes_native_ostree_booted`; `packages.yml` dnf task and both `gh.yml` tasks get `when: not hermes_native_ostree_booted.stat.exists`.
- `claude_code/tasks/install.yml`: the dnf task gets the same guard (`claude_code_ostree_booted`); the npm task is unchanged (desktops do not run this role).
- Molecule: add an `ostree` scenario (or a converge variable) that creates `/run/ostree-booted` and asserts the guarded tasks are skipped while the rest converges.
- README requirements note: on bootc hosts the image must already carry the packages.

## Control repo

### Inventory

```yaml
    hypr_desktops:
      hosts:
        hypr-test:
          ansible_host: 192.168.70.14
```

`alienware` joins in Phase 4.

### `group_vars/hypr_desktops/`

- `connection.yml`: `ansible_user: dwallace`.
- `hermes.yml`:
  ```yaml
  hermes_native_user: hermes
  hermes_native_workspace_dir: /home/hermes/workspace
  hermes_native_git_user_name: "Hermes"
  hermes_native_git_user_email: "hermes@wallace.boston"
  hermes_native_anthropic_api_key: "{{ vault_hermes_native_anthropic_api_key }}"
  hermes_native_api_server_key: "{{ vault_hermes_api_server_key }}"
  hermes_native_api_server_model_name: hermes-desktop
  hermes_native_dashboard_password: "{{ vault_hermes_dashboard_basic_auth_password }}"
  hermes_native_gh_token: "{{ vault_hermes_native_gh_token }}"
  hermes_native_dashboard_host: "127.0.0.1"
  hermes_native_api_server_host: "127.0.0.1"
  hermes_native_dashboard_traefik_enabled: false
  hermes_native_nopasswd_sudo: true
  hermes_native_sudo_commands: [/usr/bin/systemctl, /usr/bin/podman, /usr/bin/journalctl]
  hermes_native_approvals_mode: smart
  hermes_native_approvals_cron_mode: allow
  ```
- `litellm.yml`:
  ```yaml
  litellm_master_key: "{{ vault_litellm_master_key }}"
  litellm_models:
    - { name: claude-sonnet, model: anthropic/claude-sonnet-4-6 }
    - { name: claude-opus,   model: anthropic/claude-opus-4-1 }
  # Ollama entries are generated from ollama_models:
  #   { name: <model without tag>, model: ollama/<model>, api_base: http://ollama:11434 }
  ```
- `ollama.yml`: `ollama_models: [llama3.1:8b, qwen2.5-coder:7b, nomic-embed-text]`.
- `flatpaks.yml`: `desktop_flatpaks: [org.mozilla.firefox, org.libreoffice.LibreOffice, org.mozilla.Thunderbird, md.obsidian.Obsidian, dev.zed.Zed]`.
- `vault.yml` (encrypted): the four Hermes values copied from `host_vars/ai-master/vault.yml` by `ansible-vault view` piped into `ansible-vault encrypt`, plus `vault_litellm_master_key` from `openssl rand -hex 32`. Nothing is printed to the terminal or logged.

`host_vars/hypr-test/ollama.yml`: `ollama_models: [qwen2.5:0.5b, nomic-embed-text]` (CPU-only VM, 6 GiB).

### Playbook `playbooks/fedora-hypr-desktop.yml`

```yaml
- name: Configure atomic-hyprland desktops — AI services and Hermes
  hosts: hypr_desktops
  become: true
  pre_tasks:
    - name: Ensure this is a bootc host (the image carries the packages)
      ansible.builtin.stat:
        path: /run/ostree-booted
      register: hypr_ostree
    - name: Assert bootc
      ansible.builtin.assert:
        that: hypr_ostree.stat.exists
        fail_msg: "fedora-hypr-desktop.yml targets atomic-hyprland (bootc) hosts only"
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
```

`playbooks/tasks/hypr-desktop/litellm.yml`: directory `/etc/litellm` (0750 root), template `config.yaml` (model_list from `litellm_models` plus one entry per `ollama_models`; `general_settings.master_key: os.environ/LITELLM_MASTER_KEY`), template `env` (0600: `ANTHROPIC_API_KEY`, `LITELLM_MASTER_KEY`), `systemctl daemon-reload` when either changed, `litellm.service` enabled and started, handler restarts on change.

`playbooks/tasks/hypr-desktop/ollama.yml`: `ollama.service` started; `ansible.builtin.wait_for` port 11434 on 127.0.0.1; `ansible.builtin.uri` GET `/api/tags`; for each model in `ollama_models` not in `json.models[*].name`, `ansible.builtin.command: podman exec ollama ollama pull <model>` (`changed_when: true`); models already present are skipped, so the second run changes nothing.

`playbooks/tasks/hypr-desktop/flatpaks.yml`: `community.general.flatpak` with `name: "{{ desktop_flatpaks }}"`, `method: system`, `remote: flathub`, `state: present`.

`requirements.yml`: `danmwallace.fedora` and `danmwallace.hermes` floors raised to the new releases.

## Testing

- Image: `just test` with the smoke additions above; both role molecule scenarios.
- Hermes collection: molecule with the ostree case; ansible-lint.
- Control repo: `make lint`; `make check PLAYBOOK=playbooks/fedora-hypr-desktop.yml` (check mode with diff) before the real run; a second real run reports `changed=0`.
- VM acceptance over SSH: `systemctl is-active ollama litellm hermes-agent hermes-dashboard`; `curl -s 127.0.0.1:11434/api/tags` lists `qwen2.5:0.5b` and `nomic-embed-text`; `curl -s -H "Authorization: Bearer <key>" 127.0.0.1:4000/v1/models` lists `claude-sonnet`, `claude-opus`, `qwen2.5`, `nomic-embed-text`; one chat completion against `qwen2.5` returns text; `curl -s -u hermes:<pw> 127.0.0.1:9119` answers; `flatpak list --app` shows five apps; `claude --version` is `2.1.289`.
- Dan at virt-viewer: Firefox launches from Wofi as a Flatpak.

## Rollout order

1. Role 1.3.0 (PR, tag). 2. Hermes 1.4.0 (PR, tag). 3. Image rebuild, `just test`, push. 4. `bootc upgrade` and reboot on hypr-test (announced). 5. Control repo: inventory, vars, vault, playbook; `make check`; real run; second run. 6. Acceptance.

## Rollback

`bootc rollback` for the image. The playbook's effects (files under `/etc/litellm`, the `hermes` user and its units, Flatpaks, pulled models under `/var/lib/ollama`) are reversible by hand and harmless if left.

## Out of scope

GPU attachment (Phase 4), CI and signing (Phase 3), the Alienware, Hermes routed through LiteLLM, Discord gateway, Waybar modules for local models, cleanup of `group_vars/desktop`.
