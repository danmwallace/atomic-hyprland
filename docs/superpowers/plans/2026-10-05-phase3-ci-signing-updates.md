# Phase 3: CI, Signing and Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitHub Actions the sole, signing publisher of `ghcr.io/danmwallace/atomic-hyprland`, make the image refuse unsigned copies of itself, stage updates nightly without rebooting, and let Renovate propose digest bumps.

**Architecture:** One workflow job calls the existing `just` recipes (check-kernel, build, test) and, off pull requests, pushes tags computed by a small testable script and signs by digest with a cosign keypair. The image gains a `sigstoreSigned` policy entry, a `registries.d` file and the public key; a systemd drop-in turns the shipped bootc timer into stage-only. Renovate watches the four places versions are pinned.

**Tech Stack:** GitHub Actions, podman/buildah on `ubuntu-latest`, cosign 3.1.3 (legacy simple-signing flags), skopeo, containers/image policy.json, systemd drop-ins, Renovate custom regex managers, actionlint, bash tests.

**Spec:** `docs/superpowers/specs/2026-10-05-phase3-ci-signing-updates-design.md`

## Global Constraints

- Branch `dw/phase3` in `~/Code/atomic-hyprland`; Conventional Commits, first line ≤ 72 chars, imperative.
- Published tags: `44`, `44-<version>`, `latest` on `main`/nightly/dispatch-from-main; `dev-<branch>` (slashes → `-`) on dispatch from any other branch; nothing on `pull_request`. `<version>` = `YYYYMMDD-<short sha>`.
- Cosign flags verbatim: `cosign sign -y --new-bundle-format=false --use-signing-config=false --key env://COSIGN_PRIVATE_KEY <image>@<digest>`; verify with `cosign verify --new-bundle-format=false --key cosign.pub <image>@<digest>`; cosign pinned `v3.1.3`.
- Policy entry for `ghcr.io/danmwallace/atomic-hyprland`: `sigstoreSigned`, `keyPaths: ["/etc/pki/containers/atomic-hyprland.pub"]`, `signedIdentity: matchRepository`. The base's catch-all `""` docker scope must survive.
- `/etc/containers/policy.json` is edited with `jq` in `build/30-policy.sh`, never shipped as a static file.
- Public key: repo root `cosign.pub`, image `/etc/pki/containers/atomic-hyprland.pub`, mode 0644. Private key: GitHub secret `COSIGN_PRIVATE_KEY`, backup `vault_atomic_hyprland_cosign_key` in the control repo vault. `cosign.key` is git-ignored and never printed.
- Updates: `bootc-fetch-apply-updates.timer` enabled, drop-in `stage-only.conf` replaces `ExecStart` with `/usr/bin/bootc upgrade --quiet`; `rpm-ostreed-automatic.timer` disabled.
- Actions pinned by full sha with a version comment: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`, `extractions/setup-just@53165ef7e734c5c07cb06b3c8e7b647c5aa16db3 # v4`, `sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6 # v4.1.2`.
- The workflow calls `just` recipes and never re-implements them.
- Shell scripts: 4-space indent, `set -euo pipefail` (tests use `set -uo pipefail` so every check runs). YAML/JSON: 2-space indent. LF, trailing newline, no trailing whitespace.
- Prerequisite before Task 2: `cosign.pub` exists at the repo root (Dan generates the pair; see "Before starting").

## Review Focus

1. **Runner disk exhaustion.** A build that fills the runner's disk fails mid-layer with an opaque "no space left" error. Expected: the free-disk step runs first and `df -h` is in the log so the failure is diagnosable. Pinned by Task 5's actionlint pass plus the first PR run in Task 8 (watch `df` output).
2. **Nightly on an unchanged repo.** `schedule` runs have `GITHUB_REF=refs/heads/main`; the tag script must treat them as main, else a nightly pushes a `dev-main` tag. Pinned by `tests/test-ci-tags.sh` "nightly" case (Task 1).
3. **Branch names with slashes.** A dispatch from `dw/phase3` must produce the tag `dev-dw-phase3`, not a tag with a slash that the registry rejects. Pinned by `tests/test-ci-tags.sh` "dispatch branch with slash" case (Task 1).
4. **Empty signing secret.** A fork or a mis-set secret gives cosign an empty key and a confusing error after a successful push. Expected: `just sign` fails immediately with "COSIGN_PRIVATE_KEY is not set". Pinned by Task 4's guard test.
5. **Policy script run twice.** If `30-policy.sh` ever runs on a policy that already has our entry (a future base that includes it, or a re-run), the result must still be exactly one `sigstoreSigned` requirement. Pinned by the smoke check `length == 1` (Task 2), which `jq` assignment guarantees because it replaces rather than appends.

## Before starting (Dan, in a real terminal)

```
sudo dnf install cosign
cd ~/Code/atomic-hyprland && git checkout dw/phase3
COSIGN_PASSWORD= cosign generate-key-pair
gh secret set COSIGN_PRIVATE_KEY -R danmwallace/atomic-hyprland < cosign.key
ls -l cosign.pub cosign.key
```

Leave `cosign.key` in place until Task 7 has stored the vault backup; Task 7 ends by deleting it.

---

### Task 1: Tag computation script

**Files:**
- Create: `build/ci-tags.sh`
- Create: `tests/test-ci-tags.sh`
- Modify: `justfile` (the `test` recipe gains a host-side line)

**Interfaces:**
- Produces: `build/ci-tags.sh EVENT REF VERSION` prints the tags to push, one per line, nothing for `pull_request`. Consumed by the workflow in Task 5.

- [ ] **Step 1: Write the failing test**

`tests/test-ci-tags.sh`:

```bash
#!/usr/bin/bash
# Host-side: bash tests/test-ci-tags.sh (run from the repo root)
set -uo pipefail

fail=0
expect() {
    # expect DESC WANT CMD...   compares CMD's stdout+stderr to WANT exactly
    local desc="$1" want="$2"
    shift 2
    local got
    got="$("$@" 2>&1)"
    if [ "$got" = "$want" ]; then
        echo "ok    $desc"
    else
        echo "FAIL  $desc"
        printf '  want: %q\n  got:  %q\n' "$want" "$got"
        fail=1
    fi
}

s=build/ci-tags.sh
v=20261005-abc1234
expect "push to main"                  $'44\n44-20261005-abc1234\nlatest' "$s" push             refs/heads/main      "$v"
expect "nightly is main"               $'44\n44-20261005-abc1234\nlatest' "$s" schedule         refs/heads/main      "$v"
expect "dispatch from main"            $'44\n44-20261005-abc1234\nlatest' "$s" workflow_dispatch refs/heads/main     "$v"
expect "dispatch branch with slash"    "dev-dw-phase3"                     "$s" workflow_dispatch refs/heads/dw/phase3 "$v"
expect "dispatch plain branch"         "dev-fix-waybar"                    "$s" workflow_dispatch refs/heads/fix-waybar "$v"
expect "pull request prints nothing"   ""                                  "$s" pull_request     refs/pull/12/merge   "$v"
expect "missing version is an error"   "build/ci-tags.sh: line 6: 3: version" "$s" push refs/heads/main

exit "$fail"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/Code/atomic-hyprland && bash tests/test-ci-tags.sh`
Expected: seven `FAIL` lines, each `got:` containing `No such file or directory`; exit 1.

- [ ] **Step 3: Write the script**

`build/ci-tags.sh`:

```bash
#!/usr/bin/bash
# Usage: ci-tags.sh EVENT REF VERSION
# Prints the tags CI pushes, one per line. pull_request pushes nothing.
# main (push, nightly, dispatch) gets the release tags; any other branch gets
# a single dev-<branch> tag so a branch can be tried on the VM before merging.
set -euo pipefail
event="${1:?event}"; ref="${2:?ref}"; version="${3:?version}"

[ "$event" = pull_request ] && exit 0

if [ "$ref" = refs/heads/main ]; then
    printf '%s\n' 44 "44-${version}" latest
else
    branch="${ref#refs/heads/}"
    printf 'dev-%s\n' "${branch//\//-}"
fi
```

Then `chmod +x build/ci-tags.sh`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash tests/test-ci-tags.sh`
Expected: seven `ok` lines, exit 0. If "missing version is an error" fails only on the line number in the message, fix the expected string to the actual line number of the `version=` assignment (bash reports the line of the `${3:?}` expansion).

- [ ] **Step 5: Wire it into `just test`**

In `justfile`, change the `test` recipe to:

```
# Host-side CI helper tests, then the in-image smoke + dotfile sync tests
test:
    bash tests/test-ci-tags.sh
    podman run --rm -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/image-smoke.sh
    podman run --rm -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/test-sync-dotfiles.sh
```

Run: `just test 2>&1 | head -8`
Expected: the seven `ok` lines first, then the smoke test output begins.

- [ ] **Step 6: Commit**

```bash
git add build/ci-tags.sh tests/test-ci-tags.sh justfile
git commit -m "feat(ci): add tag computation script with tests"
```

---

### Task 2: Trust policy in the image

**Files:**
- Modify: `build/30-policy.sh`
- Create: `files/etc/containers/registries.d/atomic-hyprland.yaml`
- Modify: `Containerfile` (one `COPY` after `COPY files/ /`)
- Modify: `.gitignore`
- Modify: `justfile` (`test` passes `PUBKEY_SHA256`)
- Modify: `tests/image-smoke.sh` (replace the `insecureAcceptAnything` check)
- Add: `cosign.pub` (generated by Dan; this task commits it)

**Interfaces:**
- Consumes: `cosign.pub` at the repo root (prerequisite).
- Produces: `/etc/pki/containers/atomic-hyprland.pub` in the image; `PUBKEY_SHA256` env var contract between `just test` and the smoke test.

- [ ] **Step 1: Confirm the prerequisite**

Run: `test -s cosign.pub && openssl pkey -pubin -in cosign.pub -noout && echo ok; grep -c . cosign.key`
Expected: `ok` and a positive line count. If `cosign.pub` is missing, stop and ask Dan to run "Before starting".

- [ ] **Step 2: Replace the policy check in the smoke test with the failing Phase 3 checks**

In `tests/image-smoke.sh`, replace the line

```bash
check jq -e '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"][0].type == "insecureAcceptAnything"' /etc/containers/policy.json
```

with:

```bash
# Phase 3: trust policy. Our scope demands a cosign signature; the base's
# catch-all "" docker scope must survive, it is what lets Ollama and LiteLLM pull.
policy=/etc/containers/policy.json
scope='.transports.docker["ghcr.io/danmwallace/atomic-hyprland"]'
check jq -e "${scope} | length == 1" "$policy"
check jq -e "${scope}[0].type == \"sigstoreSigned\"" "$policy"
check jq -e "${scope}[0].keyPaths | type == \"array\" and length >= 1" "$policy"
check jq -e "${scope}[0].signedIdentity.type == \"matchRepository\"" "$policy"
check jq -e '.transports.docker[""][0].type == "insecureAcceptAnything"' "$policy"
for key in $(jq -r "${scope}[0].keyPaths[]? // empty" "$policy"); do
    check test -f "$key"
    check test "$(stat -c %a "$key")" = 644
    check openssl pkey -pubin -in "$key" -noout
done
# The key in the image must be the key in the repo; just test passes the sha.
check test "$(sha256sum /etc/pki/containers/atomic-hyprland.pub 2>/dev/null | cut -d' ' -f1)" = "${PUBKEY_SHA256:?set by just test}"
reg=/etc/containers/registries.d/atomic-hyprland.yaml
check test -f "$reg"
check bash -c "yq -e '.docker[\"ghcr.io/danmwallace/atomic-hyprland\"][\"use-sigstore-attachments\"] == true' $reg"
check bash -c "test \"\$(yq '.docker | keys | length' $reg)\" = 1"
```

- [ ] **Step 3: Run the smoke test against the current image to verify the new checks fail**

Run: `podman run --rm -e PUBKEY_SHA256="$(sha256sum cosign.pub | cut -d' ' -f1)" -v ./tests:/tests:ro,Z ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/image-smoke.sh | grep -E "FAIL|^ok.*(policy|registries|pki)" `
Expected: `FAIL` for `length == 1`? No: the current entry has length 1, so that passes; `FAIL` for `sigstoreSigned`, `keyPaths`, `matchRepository`, the sha256 comparison, `test -f $reg` and both `yq` checks. The `""` catch-all check passes. Exit status of the whole script is 1.

- [ ] **Step 4: Write the registries.d file**

`files/etc/containers/registries.d/atomic-hyprland.yaml`:

```yaml
# Fetch cosign signatures stored as OCI attachments for our image. Without
# this, every pull fails with "no signatures found" once policy.json
# requires sigstoreSigned.
docker:
  ghcr.io/danmwallace/atomic-hyprland:
    use-sigstore-attachments: true
```

- [ ] **Step 5: Rewrite `build/30-policy.sh`**

```bash
#!/usr/bin/bash
# Require a cosign signature for our own image. The ublue base ships
# default=reject plus a catch-all "" docker scope of insecureAcceptAnything,
# so unlisted registries (docker.io, ghcr.io/berriai) still pull unsigned;
# our more specific scope overrides the catch-all for our repository only.
# The key is copied to /etc/pki/containers by the Containerfile; the
# registries.d file that enables fetching sigstore attachments is in files/.
set -euo pipefail
policy=/etc/containers/policy.json
tmp="$(mktemp)"
jq '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"] = [{
      "type": "sigstoreSigned",
      "keyPaths": ["/etc/pki/containers/atomic-hyprland.pub"],
      "signedIdentity": {"type": "matchRepository"}
    }]' "${policy}" > "${tmp}"
install -m 0644 "${tmp}" "${policy}"
rm -f "${tmp}"
```

- [ ] **Step 6: Copy the public key in the Containerfile and ignore the private key**

In `Containerfile`, directly after the line `COPY files/ /`, add:

```dockerfile
COPY --chmod=0644 cosign.pub /etc/pki/containers/atomic-hyprland.pub
```

Append to `.gitignore`:

```
cosign.key
```

- [ ] **Step 7: Pass the sha from `just test`**

In `justfile`, change the smoke-test line of the `test` recipe to:

```
    podman run --rm -e PUBKEY_SHA256="$(sha256sum cosign.pub | cut -d' ' -f1)" \
        -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/image-smoke.sh
```

- [ ] **Step 8: Build and run the tests**

Run: `just build 2>&1 | tail -3 && just test 2>&1 | grep -E "FAIL|^ok.*(policy|registries|pki|PUBKEY)" ; just test > /dev/null; echo "rc=$?"`
Expected: build ends with the image id and `bootc container lint` output; no `FAIL` lines; `rc=0`.

- [ ] **Step 9: Verify git sees the key files correctly**

Run: `git status --short; git check-ignore cosign.key`
Expected: `cosign.pub` listed as untracked (to be added), `cosign.key` printed by `check-ignore` and absent from status.

- [ ] **Step 10: Commit**

```bash
git add cosign.pub .gitignore Containerfile build/30-policy.sh files/etc/containers/registries.d/atomic-hyprland.yaml justfile tests/image-smoke.sh
git commit -m "feat(image): require a cosign signature for our own image

Replaces the Phase 1 insecureAcceptAnything entry, which was never needed:
the ublue base's catch-all docker scope already accepted it."
```

---

### Task 3: Stage-only updates

**Files:**
- Create: `files/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/stage-only.conf`
- Modify: `build/40-finalize.sh`
- Modify: `tests/image-smoke.sh`

**Interfaces:** none shared.

- [ ] **Step 1: Write the failing smoke checks**

Append to `tests/image-smoke.sh`, before the final `exit "$fail"`:

```bash
# Phase 3: stage-only updates. One updater (bootc), staged, never auto-rebooted.
check test "$(systemctl is-enabled bootc-fetch-apply-updates.timer 2>/dev/null)" = enabled
check test "$(systemctl is-enabled rpm-ostreed-automatic.timer 2>/dev/null)" = disabled
dropin=/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/stage-only.conf
check test -f "$dropin"
check test "$(stat -c %a "$dropin" 2>/dev/null)" = 644
# The drop-in must reset ExecStart and set the stage-only command.
check grep -qx 'ExecStart=' "$dropin"
check grep -qx 'ExecStart=/usr/bin/bootc upgrade --quiet' "$dropin"
check bash -c '! grep -q -- --apply '"$dropin"
# systemctl cat lists the drop-in only if the directory name matches the unit.
check bash -c 'systemctl cat bootc-fetch-apply-updates.service | grep -q stage-only.conf'
```

- [ ] **Step 2: Run against the current image to verify they fail**

Run: `podman run --rm -e PUBKEY_SHA256=x -v ./tests:/tests:ro,Z ghcr.io/danmwallace/atomic-hyprland:44 bash /tests/image-smoke.sh | grep -E "bootc-fetch|rpm-ostreed|stage-only|dropin"`
Expected: every one of these lines is `FAIL` (timer disabled, rpm-ostree enabled, no drop-in).

- [ ] **Step 3: Write the drop-in**

`files/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/stage-only.conf`:

```ini
# Stage only. The shipped unit runs `bootc upgrade --apply`, which reboots as
# soon as an update is staged. A desktop reboots when its user decides; the
# staged deployment becomes the default at the next reboot.
[Service]
ExecStart=
ExecStart=/usr/bin/bootc upgrade --quiet
```

- [ ] **Step 4: Enable and disable the timers in finalize**

In `build/40-finalize.sh`, after `systemctl set-default graphical.target`, add:

```bash
# bootc stages updates (drop-in makes it stage-only); rpm-ostree's updater
# would race it for the same deployment slot, so only one is enabled.
systemctl enable bootc-fetch-apply-updates.timer
systemctl disable rpm-ostreed-automatic.timer
```

- [ ] **Step 5: Build and run the tests**

Run: `just build 2>&1 | tail -2 && just test 2>&1 | grep -E "FAIL|bootc-fetch|rpm-ostreed|stage-only"; just test > /dev/null; echo "rc=$?"`
Expected: all listed lines `ok`, no `FAIL`, `rc=0`.

- [ ] **Step 6: Commit**

```bash
git add files/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/stage-only.conf build/40-finalize.sh tests/image-smoke.sh
git commit -m "feat(image): stage updates nightly with bootc, never auto-reboot"
```

---

### Task 4: justfile: CI version, remove push, add sign

**Files:**
- Modify: `justfile`
- Create: `tests/test-justfile.sh`

**Interfaces:**
- Produces: `just sign [tag]` (default tag `44`), requires `COSIGN_PRIVATE_KEY`; `IMAGE_VERSION` env overrides the computed version. Consumed by the workflow in Task 5.

- [ ] **Step 1: Write the failing tests**

`tests/test-justfile.sh`:

```bash
#!/usr/bin/bash
# Host-side: bash tests/test-justfile.sh (run from the repo root)
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

# CI sets IMAGE_VERSION; the justfile must use it verbatim.
check test "$(IMAGE_VERSION=20261005-abc1234 just --evaluate version)" = 20261005-abc1234
# Locally the computed version still has the date-sha shape.
check bash -c 'just --evaluate version | grep -Eq "^[0-9]{8}-[0-9a-f]{7,}(-dirty)?$"'
# CI is the only publisher.
check bash -c '! just --summary | grep -qw push'
check bash -c 'just --summary | grep -qw sign'
# An empty key must fail before any network call, with a clear message.
check bash -c 'COSIGN_PRIVATE_KEY= just sign 2>&1 | grep -q "COSIGN_PRIVATE_KEY is not set"'
check bash -c '! COSIGN_PRIVATE_KEY= just sign >/dev/null 2>&1'
# The recipe signs by digest with the legacy flags bootc can verify.
check bash -c 'just -n sign 2>&1 | grep -q -- "--new-bundle-format=false --use-signing-config=false"'
check bash -c 'just -n sign 2>&1 | grep -q "env://COSIGN_PRIVATE_KEY"'
check bash -c 'just -n sign 2>&1 | grep -q "cosign verify --new-bundle-format=false --key cosign.pub"'
check bash -c 'just -n sign dev-x 2>&1 | grep -q "docker://ghcr.io/danmwallace/atomic-hyprland:dev-x"'

exit "$fail"
```

- [ ] **Step 2: Run to verify it fails**

Run: `bash tests/test-justfile.sh`
Expected: first check `FAIL` (version ignores the env), second `ok`, `push` check `FAIL`, every `sign` check `FAIL` (no such recipe); exit 1.

- [ ] **Step 3: Edit the justfile**

Replace the `version` line with:

```
# CI passes IMAGE_VERSION so the label, the tag and the stamp agree; locally it
# is computed, with -dirty when the tree has uncommitted changes.
version := env("IMAGE_VERSION", `date -u +%Y%m%d` + "-" + `git rev-parse --short HEAD` + `test -z "$(git status --porcelain)" || echo -dirty`)
```

Delete the `push` recipe and its two comment lines. In its place add:

```
# Sign the pushed image by digest and verify the signature. Signing by digest
# covers every tag pointing at it. The two =false flags produce the legacy
# simple-signing payload, the only format bootc/podman/skopeo verify today.
# Needs cosign 3.1.3 and COSIGN_PRIVATE_KEY in the environment (CI secret).
sign tag=tag:
    test -n "${COSIGN_PRIVATE_KEY:-}" || { echo "COSIGN_PRIVATE_KEY is not set" >&2; exit 1; }
    digest="$(skopeo inspect docker://{{image}}:{{tag}} --format '{{{{.Digest}}')" && \
        cosign sign -y --new-bundle-format=false --use-signing-config=false \
            --key env://COSIGN_PRIVATE_KEY "{{image}}@${digest}" && \
        cosign verify --new-bundle-format=false --key cosign.pub "{{image}}@${digest}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `bash tests/test-justfile.sh`
Expected: all `ok`, exit 0.

- [ ] **Step 5: Add it to `just test` and re-run**

In the `test` recipe, after `bash tests/test-ci-tags.sh` add `    bash tests/test-justfile.sh`.

Run: `just test 2>&1 | grep -c "^ok"; just test >/dev/null; echo "rc=$?"`
Expected: a count larger than before (the smoke suite plus 7 + 10 host checks), `rc=0`.

- [ ] **Step 6: Commit**

```bash
git add justfile tests/test-justfile.sh
git commit -m "feat(just): sign recipe, CI-provided version, drop local push

CI is the sole publisher from Phase 3 on; a locally pushed image would be
unsigned and refused by every installed machine."
```

---

### Task 5: Workflow and `lint-ci`

**Files:**
- Create: `.github/workflows/build.yml`
- Modify: `justfile` (add `lint-ci`)

**Interfaces:**
- Consumes: `build/ci-tags.sh EVENT REF VERSION` (Task 1); `just sign TAG`, `IMAGE_VERSION` (Task 4); `just check-kernel`, `just build`, `just test` (existing).

- [ ] **Step 1: Add the `lint-ci` recipe (actionlint only; Task 6 adds Renovate)**

Append to `justfile`:

```
# Lint the workflow (actionlint) via podman; nothing installed locally
lint-ci:
    podman run --rm -v .:/repo:ro,Z -w /repo docker.io/rhysd/actionlint:latest -color
```

- [ ] **Step 2: Run it to verify it fails without a workflow**

Run: `just lint-ci; echo "rc=$?"`
Expected: actionlint reports that no workflow files were found under `.github/workflows` (non-zero rc). If actionlint exits 0 on an absent directory, create `.github/workflows/build.yml` containing only `name: build` and re-run; expected: an error that `"on"` and `"jobs"` are required.

- [ ] **Step 3: Write the workflow**

`.github/workflows/build.yml`:

```yaml
# Builds, tests and (off pull requests) publishes and signs the image.
# Every step calls a just recipe so a CI failure reproduces locally.
name: build

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

# A newer push to the same branch cancels the running build; nightlies are
# never cancelled.
concurrency:
  group: build-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name != 'schedule' }}

env:
  IMAGE: ghcr.io/danmwallace/atomic-hyprland

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      # ~20 GB free by default; the image is 8 GB on a 6 GB base and buildah
      # keeps both. Drop toolchains this job never uses.
      - name: Free disk space
        run: |
          sudo rm -rf /usr/local/lib/android /usr/share/dotnet /opt/ghc /usr/local/.ghcup
          df -h /

      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - name: Install just
        uses: extractions/setup-just@53165ef7e734c5c07cb06b3c8e7b647c5aa16db3 # v4
        with:
          just-version: "1.57.0"

      - name: Lint CI files
        run: just lint-ci

      - name: Version
        run: echo "IMAGE_VERSION=$(date -u +%Y%m%d)-$(git rev-parse --short HEAD)" >> "$GITHUB_ENV"

      - name: Kernel match
        run: just check-kernel

      - name: Build
        run: just build

      - name: Test
        run: just test

      - name: Tags
        id: tags
        if: github.event_name != 'pull_request'
        run: echo "tags=$(build/ci-tags.sh "$GITHUB_EVENT_NAME" "$GITHUB_REF" "$IMAGE_VERSION" | tr '\n' ' ')" >> "$GITHUB_OUTPUT"

      - name: Login to ghcr
        if: github.event_name != 'pull_request'
        run: echo "${{ github.token }}" | podman login ghcr.io -u "${{ github.actor }}" --password-stdin

      - name: Push
        if: github.event_name != 'pull_request'
        env:
          TAGS: ${{ steps.tags.outputs.tags }}
        run: |
          for t in $TAGS; do
            podman tag "$IMAGE:44" "$IMAGE:$t"
            for i in 1 2 3; do
              podman push "$IMAGE:$t" && break || sleep $((10 * i))
            done
          done

      # Pinned: bootc, podman and rpm-ostree cannot read cosign 3's new bundle
      # format yet; the sign recipe uses the legacy flags.
      - name: Install cosign
        if: github.event_name != 'pull_request'
        uses: sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6 # v4.1.2
        with:
          cosign-release: v3.1.3

      - name: Sign
        if: github.event_name != 'pull_request'
        env:
          COSIGN_PRIVATE_KEY: ${{ secrets.COSIGN_PRIVATE_KEY }}
          TAGS: ${{ steps.tags.outputs.tags }}
        run: just sign "${TAGS%% *}"
```

- [ ] **Step 4: Lint it**

Run: `just lint-ci; echo "rc=$?"`
Expected: no output from actionlint, `rc=0`. Fix any reported shellcheck or expression issue in place.

- [ ] **Step 5: Check the push loop's retry does not mask a final failure**

Run: `bash -c 'set -e; for i in 1 2 3; do false && break || sleep 0; done; echo reached'`
Expected: `reached` is printed, which shows the loop alone swallows the error. So add, after the inner loop inside the Push step, the line:

```
            skopeo inspect "docker://$IMAGE:$t" --format '{{.Digest}}'
```

This fails the step if the tag never landed. Re-run `just lint-ci`; expected `rc=0`.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/build.yml justfile
git commit -m "ci: build, test, publish and sign the image on GitHub Actions"
```

---

### Task 6: Renovate configuration

**Files:**
- Create: `renovate.json`
- Modify: `justfile` (`lint-ci` gains the validator)

**Interfaces:** none shared.

- [ ] **Step 1: Add the validator to `lint-ci` and write a deliberately invalid config**

Append to the `lint-ci` recipe:

```
    podman run --rm -v ./renovate.json:/usr/src/app/renovate.json:ro,Z \
        docker.io/renovate/renovate:latest renovate-config-validator --strict
```

Write `renovate.json` as:

```json
{
  "extends": ["config:recommended"],
  "notAnOption": true
}
```

- [ ] **Step 2: Run to verify the validator rejects it**

Run: `just lint-ci; echo "rc=$?"`
Expected: output containing `Invalid configuration option: notAnOption`, `rc` non-zero.

- [ ] **Step 3: Write the real config**

`renovate.json`:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": [
    "config:recommended",
    "helpers:pinGitHubActionDigests",
    ":dependencyDashboard"
  ],
  "timezone": "UTC",
  "schedule": ["before 6am on monday"],
  "customManagers": [
    {
      "customType": "regex",
      "description": "Digest-pinned build inputs (NAME=image:tag@sha256:...)",
      "managerFilePatterns": ["/^build/images\\.env$/"],
      "matchStrings": [
        "(?<depName>[A-Z_]+)=(?<packageName>[^:@\\s]+):(?<currentValue>[^@\\s]+)@(?<currentDigest>sha256:[a-f0-9]{64})"
      ],
      "datasourceTemplate": "docker"
    },
    {
      "customType": "regex",
      "description": "Claude Code version baked into the image",
      "managerFilePatterns": ["/^Containerfile$/"],
      "matchStrings": ["ARG CLAUDE_CODE_VERSION=(?<currentValue>\\S+)"],
      "datasourceTemplate": "npm",
      "depNameTemplate": "@anthropic-ai/claude-code"
    },
    {
      "customType": "regex",
      "description": "Quadlet container images",
      "managerFilePatterns": ["/^files/usr/share/containers/systemd/.+\\.container$/"],
      "matchStrings": ["Image=(?<depName>[^:\\s]+):(?<currentValue>\\S+)"],
      "datasourceTemplate": "docker"
    }
  ],
  "packageRules": [
    {
      "description": "Base and akmods move together; one PR, one kernel-match verdict",
      "matchFileNames": ["build/images.env"],
      "groupName": "ublue base and akmods",
      "pinDigests": true
    },
    {
      "description": "Fedora version bumps (44 -> 45) are a human decision, not a bot's",
      "matchFileNames": ["build/images.env"],
      "matchUpdateTypes": ["major", "minor", "patch"],
      "enabled": false
    },
    {
      "description": "LiteLLM publishes nightlies to the same repository",
      "matchPackageNames": ["ghcr.io/berriai/litellm"],
      "allowedVersions": "/-stable$/"
    }
  ]
}
```

- [ ] **Step 4: Validate**

Run: `just lint-ci; echo "rc=$?"`
Expected: validator prints `Config validated successfully` (and actionlint stays silent), `rc=0`. If `--strict` flags a renamed option, use the name it suggests and re-run.

- [ ] **Step 5: Prove the images.env regex matches both lines**

Run: `grep -oE '[A-Z_]+=[^:@[:space:]]+:[^@[:space:]]+@sha256:[a-f0-9]{64}' build/images.env | wc -l`
Expected: `2`.

- [ ] **Step 6: Commit**

```bash
git add renovate.json justfile
git commit -m "ci: add Renovate for image digests, actions, Claude Code and Quadlets"
```

---

### Task 7: Key backup in the control repo vault, then delete the local key

**Files:**
- Modify: `~/Code/Infrastructure/ansible-homelab-cfg/inventories/lab/group_vars/hypr_desktops/vault.yml`
- Delete: `~/Code/atomic-hyprland/cosign.key`

**Interfaces:** none shared. The vault password file is `~/Code/Infrastructure/ansible-homelab-cfg/.vault_pass`. Use VaultLib from Python (the `ansible-vault` CLI breaks on this harness's non-blocking stdio). Never print the key or the decrypted vault.

- [ ] **Step 1: Write the failing check**

Run from the control repo:

```bash
cd ~/Code/Infrastructure/ansible-homelab-cfg && python3 - <<'EOF'
from ansible.parsing.vault import VaultLib, VaultSecret
import yaml, pathlib
secret = pathlib.Path(".vault_pass").read_bytes().strip()
vl = VaultLib([("default", VaultSecret(secret))])
data = yaml.safe_load(vl.decrypt(pathlib.Path("inventories/lab/group_vars/hypr_desktops/vault.yml").read_bytes()))
print(sorted(data))
print("has_key:", "vault_atomic_hyprland_cosign_key" in data)
EOF
```

Expected: the five existing variable names and `has_key: False`.

- [ ] **Step 2: Add the key**

```bash
cd ~/Code/Infrastructure/ansible-homelab-cfg && git checkout -b dw/phase3-cosign-backup && python3 - <<'EOF'
from ansible.parsing.vault import VaultLib, VaultSecret
import yaml, pathlib
secret = pathlib.Path(".vault_pass").read_bytes().strip()
vl = VaultLib([("default", VaultSecret(secret))])
p = pathlib.Path("inventories/lab/group_vars/hypr_desktops/vault.yml")
data = yaml.safe_load(vl.decrypt(p.read_bytes()))
key = pathlib.Path.home().joinpath("Code/atomic-hyprland/cosign.key").read_text()
assert key.startswith("-----BEGIN ENCRYPTED SIGSTORE PRIVATE KEY-----"), "unexpected key format"
data["vault_atomic_hyprland_cosign_key"] = key
p.write_bytes(vl.encrypt(yaml.safe_dump(data, default_flow_style=False, width=4096)))
print("written")
EOF
```

Expected: `written`. (cosign writes the private key PEM with that header even with an empty passphrase.)

- [ ] **Step 3: Re-run the check**

Run the Step 1 script again.
Expected: six names including `vault_atomic_hyprland_cosign_key`, `has_key: True`.

- [ ] **Step 4: Confirm the file is still a vault and nothing leaked**

Run: `cd ~/Code/Infrastructure/ansible-homelab-cfg && head -1 inventories/lab/group_vars/hypr_desktops/vault.yml && git diff --stat && ! git diff | grep -q "BEGIN ENCRYPTED" && echo "no plaintext in diff"`
Expected: `$ANSIBLE_VAULT;1.1;AES256`, one file changed, `no plaintext in diff`.

- [ ] **Step 5: Commit, push, open the control-repo PR**

```bash
cd ~/Code/Infrastructure/ansible-homelab-cfg
git add inventories/lab/group_vars/hypr_desktops/vault.yml
git commit -m "chore(vault): back up the atomic-hyprland cosign signing key

The GitHub secret COSIGN_PRIVATE_KEY is the working copy; this is the
recovery copy. No task reads it."
git push -u origin dw/phase3-cosign-backup
gh pr create --fill --body "Backup of the atomic-hyprland image signing key in the hypr_desktops vault. No task reads it.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk"
```

- [ ] **Step 6: Delete the local private key and confirm the secret exists**

Run: `shred -u ~/Code/atomic-hyprland/cosign.key && gh secret list -R danmwallace/atomic-hyprland`
Expected: `COSIGN_PRIVATE_KEY` listed with an update timestamp; `cosign.key` gone (`ls` reports no such file).

---

### Task 8: README, then the first CI run on a pull request

**Files:**
- Modify: `~/Code/atomic-hyprland/README.md`

**Interfaces:** none shared.

- [ ] **Step 1: Write the failing doc check**

Run: `cd ~/Code/atomic-hyprland && grep -c "just push" README.md; grep -q "^## Publishing and trust" README.md; echo "rc=$?"`
Expected: `1` (the stale `just push` line) and `rc=1`.

- [ ] **Step 2: Update the README**

Replace the `## Local loop` block with:

```markdown
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
```

Add after the `## AI services (Phase 2)` section:

```markdown
## Publishing and trust (Phase 3)

`.github/workflows/build.yml` runs on push to `main`, nightly at 03:00 UTC,
on pull requests (build and test only) and on manual dispatch. It calls the
same `just` recipes as the local loop, pushes the tags from
`build/ci-tags.sh`, then signs the image by digest with cosign 3.1.3 using the
legacy simple-signing format, the only one bootc, podman and skopeo verify.

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
```

Append to the `## VM runbook` section:

```markdown
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
```

- [ ] **Step 3: Re-run the doc check**

Run: `grep -c "just push" README.md; grep -q "^## Publishing and trust" README.md; echo "rc=$?"`
Expected: `0` and `rc=0`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: describe CI publishing, trust, updates and the Phase 3 runbook"
```

- [ ] **Step 5: Push the branch and open the PR so the `pull_request` path runs**

```bash
git push -u origin dw/phase3
gh pr create --title "Phase 3: CI, signing and stage-only updates" --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-10-05-phase3-ci-signing-updates-design.md.

- GitHub Actions builds, tests, publishes and signs (cosign keypair, legacy simple-signing)
- Image requires a signature for its own repository; registries.d + public key shipped
- bootc stage-only update timer; rpm-ostree timer disabled
- Renovate for images.env digests, actions, Claude Code, Quadlet tags

This PR run exercises the pull_request path (build + test, no push). The push/sign path runs on merge.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01VXwJFuUeG9gAAj8A9HzWCk
EOF
)"
```

- [ ] **Step 6: Watch the run to green**

Run: `gh run list --workflow build.yml --limit 1` then `gh run watch "$(gh run list --workflow build.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status; echo "rc=$?"`
Expected: `rc=0`; the `Free disk space` step log shows `df -h /` with more than 40 GB available; `Test` step shows no `FAIL`; `Tags`, `Push`, `Sign` steps are skipped. A red run is a bug: fix on this branch with a failing test first, push, and watch again. Note the total duration in the ledger for the README's "20 to 30 minutes" claim.

---

## Post-merge rollout (after superpowers:finishing-a-development-branch)

Not plan tasks; they need `main`. Executed by the session after the merge, with Dan watching:

1. `gh run watch` the `push` run on `main` to green. From the laptop confirm the signature:
   `podman run --rm ghcr.io/danmwallace/atomic-hyprland:44 cosign verify --new-bundle-format=false --key /etc/pki/containers/atomic-hyprland.pub ghcr.io/danmwallace/atomic-hyprland:44`
   (the running image is the old one, but the key file is the same key).
2. README "Phase 3 verification" steps 1 to 6 on hypr-test. Step 6 waits for the next build (nightly or a trivial merge).
3. Dan installs the Mend Renovate GitHub App on the repo; confirm the dependency dashboard issue appears.
4. Obsidian: mark "Phase 3 CI Signing and Updates" Done; add any follow-ups.
