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
- Known gaps (deliberate, later phases): no NVIDIA, no Ollama/LiteLLM, image
  unsigned (policy allows our registry unsigned until Phase 3), the role's
  `10-theme.conf` names an SDDM theme that is not installed so SDDM uses its
  default, the default wallpaper file is missing (black background).

## AI services (Phase 2)

The image ships `ollama.service` (starts on first boot, models under
`/var/lib/ollama`) and `litellm.service`, which stays inactive until
`playbooks/fedora-hypr-desktop.yml` in ansible-homelab-cfg renders
`/etc/litellm/config.yaml` and `/etc/litellm/env`. Both bind to loopback only.
Claude Code is in the image for every user. Firefox, LibreOffice and
Thunderbird are Flatpaks installed by the same playbook.

Verified on hypr-test 2026-10-04: Ollama (CPU) with the two small models,
LiteLLM answering a completion through the local model, Hermes agent and
dashboard active under SELinux enforcing, five Flatpaks, playbook idempotent.
First boot pulls the two container images with `ai-images-pull.service`
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
Ollama and LiteLLM images pull.

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
