# Phase 3: CI, signing and updates: design

Phase 3 of the atomic-hyprland project (main spec:
`2026-10-03-atomic-hyprland-design.md`). It makes GitHub Actions the only
publisher of `ghcr.io/danmwallace/atomic-hyprland`, signs every published
image with cosign, makes every installed machine refuse unsigned images, stages
updates nightly without rebooting, and lets Renovate propose digest bumps.

## Decisions

Dan's choices, after trade-offs, 2026-10-04 and 2026-10-05:

- **CI is the sole publisher.** `just push` is removed. Local work is
  `just build` and `just test`; publishing is a merge to `main`, or a manual
  workflow dispatch from a branch, which pushes a signed `dev-<branch>` tag.
  Trade-off accepted: a 20 to 30 minute CI round trip to see a change on the VM.
- **Cosign keypair, not keyless.** containers/image can verify a keyless
  (Fulcio) signature only when the certificate carries an email or hostname
  subject. GitHub Actions identities are URIs, so no `policy.json` entry can
  match them. The main spec's "cosign keyless (OIDC)" is therefore replaced by
  a keypair: private key in a GitHub secret, public key in the repo and image.
  This is Universal Blue's model.
- **Stage only.** Updates are staged by `bootc upgrade` on a timer and take
  effect at the next reboot the user chooses. The shipped
  `bootc upgrade --apply` behaviour (auto reboot) is overridden by a drop-in.
  ublue's `rpm-ostreed-automatic.timer` is disabled so one updater owns the
  machine, and it is the one this project exists to practise.
- **Renovate**, not a hand-rolled weekly job, bumps the digests in
  `build/images.env` and the other pinned versions in the repo. Dan installs
  the Mend Renovate GitHub App once.
- **Tag format.** Published tags are `44`, `44-<version>` and `latest`, where
  `<version>` is `YYYYMMDD-<short sha>`, the format `just push` has used since
  Phase 1 (eight such tags already exist on ghcr). The main spec's
  `44-YYYYMMDD` is superseded: the sha distinguishes two builds on one day.

## Facts verified 2026-10-04 and 2026-10-05

| Item | Result |
|---|---|
| `bootc-fetch-apply-updates.service` | `ExecStart=/usr/bin/bootc upgrade --apply --quiet`; timer `OnBootSec=1h OnUnitInactiveSec=8h RandomizedDelaySec=2h`; timer disabled in the base |
| `rpm-ostreed-automatic.timer` | enabled in the base; `/etc/rpm-ostreed.conf` has `AutomaticUpdatePolicy=stage` |
| `bootc upgrade` without `--apply` | downloads and stages only ("The deployment will be applied on the next shutdown or reboot") |
| `/etc/containers/policy.json` in the base | `default: reject`, but the `docker` transport has a catch-all scope `""` set to `insecureAcceptAnything`; specific scopes for `ghcr.io/ublue-os` (sigstoreSigned, two `keyPaths`, `matchRepository`), `quay.io/toolbx-images`, Red Hat registries |
| Consequence | the Phase 1 `insecureAcceptAnything` entry for our repository was never needed; the catch-all already accepted it. The comment in `build/30-policy.sh` claiming the base would refuse our image was wrong. Ollama and LiteLLM pull via the catch-all |
| containers-policy.json(5) in the image | `sigstoreSigned` accepts `keyPath`, `keyPaths`, `keyData`, `fulcio` (requires `subjectEmail` or `subjectHostname`) and `rekorPublicKey*`; `signedIdentity` for sigstore supports `matchRepository` and `exactRepository` |
| `registries.d` | base ships `/etc/containers/registries.d/ublue-os.yaml` with `use-sigstore-attachments: true`; no `/usr/share/containers/registries.d` |
| Versions in the image | containers-common 0.67.2, skopeo 1.22.3, podman 5.8.7, bootc 1.16.13, cosign 3.1.3 (`/usr/sbin/cosign`) |
| ublue signing (`ublue-os/main` Justfile) | `cosign sign -y --new-bundle-format=false --use-signing-config=false --key env://COSIGN_PRIVATE_KEY <image>@<digest>` then `cosign verify --new-bundle-format=false --key cosign.pub <image>@<digest>`; cosign pinned to v3.1.3 via `sigstore/cosign-installer` because bootc, podman and rpm-ostree cannot read cosign 3's new bundle format (containers/container-libs#388, coreos/rpm-ostree#5509) |
| ublue workflow | `runs-on: ubuntu-26.04`, actions pinned by sha with version comments, permissions `contents: read, packages: write, id-token: write` |
| Image size | 8,216,422,329 bytes uncompressed, 266 layers; base 6,111,241,198 bytes |
| GitHub | repo public, Actions enabled with `allowed_actions: all`, no secrets yet; `gh` token has `repo, workflow, write:packages` |
| ghcr tags | `44`, `44-20261003-76f76cf`, `44-20261003-569b72f`, `44-20261004-f009e34-dirty`, `44-20261004-51b5b26`, `44-20261004-adadf02`, `44-20261004-a8210d4`, `44-20261004-7018d1e`; all unsigned |
| Existing CI conventions (collection repos) | `ubuntu-latest`, `actions/checkout@v6`, `concurrency` groups |

## Workflow `.github/workflows/build.yml`

One job, `build`, on `ubuntu-latest`.

**Triggers.** `push` to `main`; `schedule` cron `0 3 * * *` (03:00 UTC
nightly); `pull_request`; `workflow_dispatch`.

**Permissions.** `contents: read`, `packages: write`.

**Concurrency.** Group `build-${{ github.ref }}`,
`cancel-in-progress: ${{ github.event_name != 'schedule' }}`. A second push to a
branch cancels the in-flight build of that branch; a nightly is never cancelled.

**Steps.**

1. **Free disk.** `sudo rm -rf /usr/local/lib/android /usr/share/dotnet
   /opt/ghc /usr/local/.ghcup`, then `df -h /`. The runner has roughly 20 GB
   free; the build needs the base layers plus ours.
2. **Checkout** (`actions/checkout`, pinned by sha).
3. **Install just** (`extractions/setup-just`, pinned by sha).
4. **Lint CI files.** `just lint-ci` (see Testing). Fails fast on a broken
   workflow or Renovate config.
5. **Version.** `echo "IMAGE_VERSION=$(date -u +%Y%m%d)-$(git rev-parse
   --short HEAD)" >> "$GITHUB_ENV"`. The justfile's `version` variable reads
   `IMAGE_VERSION` from the environment when set, else computes it as today.
6. **Kernel match.** `just check-kernel`. Runs before the build so a drifted
   base fails in seconds.
7. **Build.** `just build`. `bootc container lint` already runs inside
   `build/90-cleanup.sh`.
8. **Test.** `just test`. The smoke tests and the dotfile sync tests. Red
   blocks the push.
9. **Login to ghcr** (`podman login ghcr.io -u ${{ github.actor }}
   --password-stdin` with `${{ github.token }}`). Skipped on `pull_request`.
10. **Push.** Skipped on `pull_request`.
    - On `push` to `main` and on `schedule`: push `44`, `44-<version>`,
      `latest`.
    - On `workflow_dispatch` from `main`: same as above.
    - On `workflow_dispatch` from any other branch: push only
      `dev-<branch>` (slashes in the branch name replaced by `-`).
    A nightly whose inputs are unchanged still pushes: the dated tag records
    that the build ran, and `44` then points at a byte-identical image, which
    bootc treats as no update.
11. **Install cosign** (`sigstore/cosign-installer`, pinned by sha,
    `cosign-release: v3.1.3`). Skipped on `pull_request`.
12. **Sign.** `just sign <tag>` with `COSIGN_PRIVATE_KEY` from the secret of
    the same name. Signs by digest and verifies. Skipped on `pull_request`.

The workflow calls `just` recipes and never re-implements them, so a CI
failure reproduces locally with the same command.

## Signing

### Key generation (Dan, once, in a real terminal)

```
sudo dnf install cosign
cd ~/Code/atomic-hyprland
COSIGN_PASSWORD= cosign generate-key-pair
```

Produces `cosign.key` (private, never committed; `.gitignore` gets a
`cosign.key` line) and `cosign.pub` (committed at the repo root). The empty
passphrase is deliberate: the key is used by an unattended runner, and a
passphrase stored in a second secret adds nothing.

### Where the halves live

| File | Location | Why |
|---|---|---|
| `cosign.pub` | repo root; `COPY cosign.pub /etc/pki/containers/atomic-hyprland.pub` in the Containerfile | verifiers need it; sits next to the base's `ublue-os.pub` |
| `cosign.key` | GitHub secret `COSIGN_PRIVATE_KEY` (`gh secret set COSIGN_PRIVATE_KEY < cosign.key`); backup as `vault_atomic_hyprland_cosign_key` in `ansible-homelab-cfg` `inventories/lab/group_vars/hypr_desktops/vault.yml` | the runner signs with it; the vault copy means a deleted secret is not a lost image |

After both copies exist, Dan deletes the local `cosign.key`.

### Rotation

Generate a new pair. Commit the new public key as `cosign-next.pub`, add it
to the image as `/etc/pki/containers/atomic-hyprland-next.pub` and to the
policy `keyPaths` list. Build and let every machine upgrade once so they
trust both keys. Replace the secret with the new private key. After the next
build, remove the old key from the repo, the image and the policy. The policy
uses `keyPaths` (plural) from day one so this is an edit, not a restructure.

### `just sign` recipe

```
# Sign the pushed image by digest and verify the signature (CI; needs
# COSIGN_PRIVATE_KEY in the environment, cosign 3.1.3)
sign tag=tag:
    digest="$(skopeo inspect docker://{{image}}:{{tag}} --format '{{{{.Digest}}')" && \
        cosign sign -y --new-bundle-format=false --use-signing-config=false \
            --key env://COSIGN_PRIVATE_KEY "{{image}}@${digest}" && \
        cosign verify --new-bundle-format=false --key cosign.pub "{{image}}@${digest}"
```

Signing by digest covers every tag that points at it, so one signature serves
`44`, `44-<version>` and `latest`. The two `false` flags produce the legacy
simple-signing payload stored as an OCI attachment, the only format
containers/image verifies today. The verify step makes a green job mean a
signed image.

## Trust policy in the image

### `build/30-policy.sh`

Still edits the base's `policy.json` with `jq`; a static replacement would
drop whatever ublue adds to their entries later. New entry:

```json
"ghcr.io/danmwallace/atomic-hyprland": [{
  "type": "sigstoreSigned",
  "keyPaths": ["/etc/pki/containers/atomic-hyprland.pub"],
  "signedIdentity": {"type": "matchRepository"}
}]
```

`matchRepository`: the signature must be for this repository, any tag or
digest. The base's catch-all `""` scope stays, so Ollama and LiteLLM pulls
are unaffected; our scope is more specific and wins for our image only.
The script's header comment is corrected (see Facts).

### `files/etc/containers/registries.d/atomic-hyprland.yaml`

```yaml
docker:
  ghcr.io/danmwallace/atomic-hyprland:
    use-sigstore-attachments: true
```

Without it the client never fetches the signature attachment and every pull
fails with "no signatures found".

### `/etc/pki/containers/atomic-hyprland.pub`

Copied from the repo-root `cosign.pub` by a `COPY` line placed next to
`COPY files/ /` in the Containerfile. Mode 0644.

### Transition

The image on hypr-test today accepts anything from our repository, so it
pulls the first signed build. From that boot on, every pull of our image must
be signed. The unsigned tag `44-20261004-7018d1e` stays on ghcr as a
permanent negative test case. The laptop's podman policy is Fedora's default
and is untouched.

## Stage-only updates

`files/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/stage-only.conf`:

```ini
# Stage only. The shipped unit runs `bootc upgrade --apply`, which reboots as
# soon as an update is staged. A desktop reboots when its user decides.
[Service]
ExecStart=
ExecStart=/usr/bin/bootc upgrade --quiet
```

`build/40-finalize.sh` adds:

```
systemctl enable bootc-fetch-apply-updates.timer
systemctl disable rpm-ostreed-automatic.timer
```

The timer schedule is the shipped one. `AutomaticUpdatePolicy=stage` in
`rpm-ostreed.conf` is left alone; it is inert without the timer.

Signature verification happens in this path: bootc fetches the sigstore
attachment and checks it against the key in `keyPaths`. An unsigned or
wrongly signed image is refused, the booted deployment stays, and the
refusal appears in `journalctl -u bootc-fetch-apply-updates.service`.

User-visible effect: none until reboot. `bootc status` shows a `staged`
entry while an update waits. A Waybar indicator is out of scope.

## Renovate

Dan installs the Mend Renovate GitHub App on `danmwallace/atomic-hyprland`.
`renovate.json` at the repo root:

- `extends`: `config:recommended`, `helpers:pinGitHubActionDigests`,
  `:dependencyDashboard`.
- `schedule`: `["before 6am on monday"]`, `timezone` `UTC`. No automerge.
- **images.env manager.** Custom regex manager on `build/images.env`,
  pattern `^(?<depName>[^=\s]+)=(?<packageName>[^:@\s]+):(?<currentValue>[^@\s]+)@(?<currentDigest>sha256:[a-f0-9]{64})$`
  with `datasourceTemplate: docker`. Package rule: `matchFileNames
  ["build/images.env"]`, `groupName: "ublue base and akmods"`,
  `pinDigests: true`, so both pins land in one PR and one CI verdict. If
  ublue publishes base and akmods hours apart, the grouped PR fails
  `check-kernel` until the second lands and Renovate refreshes it. That is
  the check working.
- **Claude Code manager.** Regex on the Containerfile line
  `^ARG CLAUDE_CODE_VERSION=(?<currentValue>\S+)$`, `datasourceTemplate: npm`,
  `depNameTemplate: @anthropic-ai/claude-code`.
- **Quadlet manager.** Regex on `files/usr/share/containers/systemd/*.container`,
  pattern `^Image=(?<depName>[^:\s]+):(?<currentValue>\S+)$`,
  `datasourceTemplate: docker`. Package rule for `ghcr.io/berriai/litellm`:
  `allowedVersions: "/-stable$/"`, since they publish nightlies on the same
  repository.
- GitHub Actions are handled by the built-in manager with sha pinning.

Every Renovate PR triggers the workflow, which builds and tests and does not
push. This closes the Phase 2 deferred minor "image tags pinned in four
places": they stay in four places, one bot watches all four.

## Repo changes

| File | Change |
|---|---|
| `.github/workflows/build.yml` | new |
| `renovate.json` | new |
| `cosign.pub` | new (Dan generates) |
| `.gitignore` | add `cosign.key` |
| `Containerfile` | `COPY cosign.pub /etc/pki/containers/atomic-hyprland.pub` |
| `build/30-policy.sh` | sigstoreSigned entry; corrected comment |
| `build/40-finalize.sh` | enable bootc timer, disable rpm-ostree timer |
| `files/etc/containers/registries.d/atomic-hyprland.yaml` | new |
| `files/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/stage-only.conf` | new |
| `justfile` | `version` honours `IMAGE_VERSION`; remove `push`; add `sign`, `lint-ci`; `test` passes the `cosign.pub` sha |
| `tests/image-smoke.sh` | checks below |
| `README.md` | CI, tags, trust and rotation, update behaviour, VM runbook; local loop loses `push` |
| `ansible-homelab-cfg` | `vault_atomic_hyprland_cosign_key` in `group_vars/hypr_desktops/vault.yml` (key backup only, no task reads it) |

## Testing

### `tests/image-smoke.sh` additions

Run inside the built image by `just test`, which passes
`PUBKEY_SHA256=$(sha256sum cosign.pub | cut -d' ' -f1)` as an environment
variable:

- policy entry for `ghcr.io/danmwallace/atomic-hyprland` has exactly one
  requirement of `type == "sigstoreSigned"`, with `keyPaths` (an array) and
  `signedIdentity.type == "matchRepository"`; no requirement of type
  `insecureAcceptAnything` remains for that scope;
- every path in `keyPaths` exists, is mode 0644, and parses with
  `openssl pkey -pubin -in <path> -noout`;
- `sha256sum /etc/pki/containers/atomic-hyprland.pub` equals `PUBKEY_SHA256`;
- `/etc/containers/registries.d/atomic-hyprland.yaml` exists and `yq` reads
  `.docker["ghcr.io/danmwallace/atomic-hyprland"]["use-sigstore-attachments"]`
  as `true`, and it is the only key under `.docker`;
- the catch-all `.transports.docker[""]` is still `insecureAcceptAnything`;
- `systemctl is-enabled bootc-fetch-apply-updates.timer` is `enabled`;
  `systemctl is-enabled rpm-ostreed-automatic.timer` is `disabled`;
- `systemctl cat bootc-fetch-apply-updates.service` contains the drop-in and
  its effective `ExecStart` lines do not contain `--apply`;
- the drop-in file is mode 0644.

### `just lint-ci`

```
# Lint the workflow and the Renovate config (no local installs)
lint-ci:
    podman run --rm -v .:/repo:ro,Z -w /repo docker.io/rhysd/actionlint:latest -color
    podman run --rm -v ./renovate.json:/usr/src/app/renovate.json:ro,Z \
        docker.io/renovate/renovate:latest renovate-config-validator
```

### The first real run

A workflow file has no test but its first run. The plan ends with: merge to
`main`, watch the run with `gh run watch`, and treat any failure as a bug to
fix on a follow-up branch before the VM runbook starts.

### VM runbook (hypr-test, as root via sudo)

1. **First signed upgrade.** `bootc upgrade`, reboot. `bootc status` shows the
   new version booted and `44-20261004-7018d1e`'s image as rollback. Policy
   has the `sigstoreSigned` entry; bootc timer enabled; rpm-ostree timer
   disabled.
2. **Positive signature check.** `cosign verify --new-bundle-format=false
   --key /etc/pki/containers/atomic-hyprland.pub
   ghcr.io/danmwallace/atomic-hyprland:44` succeeds.
3. **Negative check, read-only.** `skopeo copy
   docker://ghcr.io/danmwallace/atomic-hyprland:44-20261004-7018d1e
   dir:/tmp/unsigned` fails with a signature error.
4. **Negative check, real path.** `bootc switch
   ghcr.io/danmwallace/atomic-hyprland:44-20261004-7018d1e` fails at the pull
   with the same error; `bootc status` is unchanged. Recovery if it ever did
   stage: `bootc switch ghcr.io/danmwallace/atomic-hyprland:44`.
5. **Deliberate rollback.** `bootc rollback`, reboot. `bootc status` shows the
   Phase 2 image booted and the signed image as rollback. Log in, confirm
   Ollama answers (`curl -s 127.0.0.1:11434/api/tags`). `bootc rollback`
   again, reboot, back on the signed image with no download.
6. **Timer check.** `systemctl list-timers bootc-fetch-apply-updates.timer`
   shows a next run. After the next CI build: `systemctl start
   bootc-fetch-apply-updates.service`; `bootc status` shows a staged
   deployment; `uptime` shows no reboot.

## Rollout order

1. Dan: generate the keypair, set the GitHub secret, commit `cosign.pub`,
   store the vault backup, delete the local private key, install the Renovate
   app.
2. Branch `dw/phase3`: all repo changes; `just lint-ci`, `just build`,
   `just test` green locally.
3. Fresh-context review; fix pass; merge to `main` locally and push.
4. Watch the first `main` run to green. Confirm `44` is signed from the
   laptop with `cosign verify` via `podman run` of the image (the laptop has no
   cosign).
5. VM runbook steps 1 to 6.
6. Obsidian: close "Phase 3 CI Signing and Updates".

## Rollback

- A broken workflow publishes nothing: the push step runs only after build
  and tests pass, and the sign step verifies before the job succeeds.
- A machine that refuses the new image because of a policy mistake keeps
  running the booted deployment; `bootc rollback` is not even needed. The fix
  is a corrected build. If a signed but broken image is booted, `bootc
  rollback` returns to the previous deployment.
- If the signing key is lost (secret and vault both), machines already on a
  signed image cannot be upgraded by any new build. Recovery is a manual
  `bootc switch` to a new repository with a new key, which is why the vault
  backup exists.

## Out of scope

SBOM and provenance attestations; Secure Boot and kernel module signing; a
Waybar pending-update indicator; multi-arch builds; Renovate coverage of the
`danmwallace.fedora` and `danmwallace.hermes` collection versions
(`build/requirements.yml` pins a git tag, which Renovate's `git-tags`
datasource could read, but it is left for later); the NVIDIA layer (Phase 4).
