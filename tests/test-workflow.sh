#!/usr/bin/bash
# Host-side: bash tests/test-workflow.sh (repo root). Structural checks on the
# workflow for the push/sign path, which only runs on main and so has no
# other test before its first real run.
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

wf=.github/workflows/build.yml
step() { # step NAME KEY  -> prints that key of the named step
    python3 -c '
import sys, yaml
steps = yaml.safe_load(open(sys.argv[1]))["jobs"]["build"]["steps"]
hits = [s for s in steps if s.get("name") == sys.argv[2]]
sys.exit(1) if not hits else print(hits[0].get(sys.argv[3], ""))' "$wf" "$1" "$2"
}
idx() { # idx NAME -> 1-based position of the step
    python3 -c '
import sys, yaml
names = [s.get("name") for s in yaml.safe_load(open(sys.argv[1]))["jobs"]["build"]["steps"]]
print(names.index(sys.argv[2]) + 1)' "$wf" "$1"
}
top() { python3 -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))[sys.argv[2]][sys.argv[3]])' "$wf" "$1" "$2"; }
export -f step idx top
export wf

# cosign reads ~/.docker/config.json, not podman's auth.json: log in with both.
check bash -c "step 'Login to ghcr' run | grep -q 'podman login ghcr.io'"
check bash -c "step 'Login to ghcr' run | grep -q 'docker login ghcr.io'"
# Order: push the unique tag, sign it, only then re-point 44 and latest, so no
# release tag ever names an unsigned digest.
check test "$(idx 'Push version tag')" -lt "$(idx 'Install cosign')"
check test "$(idx 'Install cosign')" -lt "$(idx 'Sign')"
check test "$(idx 'Sign')" -lt "$(idx 'Push release tags')"
# Both push steps go through the script whose retry and digest checks are tested.
check bash -c "step 'Push version tag' run | grep -q 'build/ci-push.sh'"
check bash -c "step 'Push release tags' run | grep -q 'build/ci-push.sh'"
# Sign signs the tag that was just pushed.
check bash -c "step 'Sign' run | grep -q 'just sign'"
# A main run is never cancelled mid-publish; branch and PR runs are.
check bash -c "top concurrency cancel-in-progress | grep -q \"github.ref != 'refs/heads/main'\""
# Nothing publishes on pull requests.
for s in 'Login to ghcr' 'Push version tag' 'Install cosign' 'Sign' 'Push release tags'; do
    check bash -c "step '$s' if | grep -q \"github.event_name != 'pull_request'\""
done

# setup-just downloads from GitHub releases, which return transient 504s: a
# second attempt runs only when the first failed
wf=.github/workflows/build.yml
check bash -c "grep -A3 'name: Install just\$' $wf | grep -q 'continue-on-error: true'"
check bash -c "grep -A2 'name: Install just (retry)' $wf | grep -q \"if: steps.just.outcome == 'failure'\""
check bash -c "grep -A1 'name: Install just\$' $wf | grep -q 'id: just'"

# The signing key has no passphrase; say so instead of relying on empty stdin.
check python3 -c '
import sys, yaml
steps = yaml.safe_load(open(sys.argv[1]))["jobs"]["build"]["steps"]
env = [s for s in steps if s.get("name") == "Sign"][0].get("env", {})
sys.exit(0 if env.get("COSIGN_PASSWORD") == "" else 1)' "$wf"
# Host tests need no image: they run before the 15-minute build, so a broken
# script fails in a minute. After the build only the image tests run.
check bash -c "step 'Host tests' run | grep -qx 'just test-host'"
check test "$(idx 'Host tests')" -lt "$(idx 'Build')"
check bash -c "step 'Test' run | grep -qx 'just test-image'"
# ci-tags.sh failing (a dispatch on a tag) must fail the Tags step; a process
# substitution would swallow its exit status.
check bash -c "! step 'Tags' run | grep -q '< <(build/ci-tags.sh'"
check bash -c "step 'Tags' run | grep -q 'build/ci-tags.sh'"

exit "$fail"
