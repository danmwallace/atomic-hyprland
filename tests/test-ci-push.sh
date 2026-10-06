#!/usr/bin/bash
# Host-side: bash tests/test-ci-push.sh (repo root). Exercises build/ci-push.sh
# with stub podman/skopeo so the push path is tested before it ever runs on
# main. The stubs read their behaviour from STUB_MODE.
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

stubs="$(mktemp -d)"
trap 'rm -rf "$stubs"' EXIT
cat > "$stubs/podman" <<'STUB'
#!/usr/bin/bash
# STUB_MODE: fail | ok | flaky (fails twice, then ok) | stale (ok, registry differs)
case "$1" in
    tag) exit 0 ;;
    push)
        echo push >> "$STUB_LOG"
        n=$(grep -c push "$STUB_LOG")
        case "$STUB_MODE" in
            fail) exit 1 ;;
            flaky) [ "$n" -ge 3 ] || exit 1 ;;
        esac
        # --digestfile FILE is the second and third argument
        echo "sha256:new" > "$3"
        exit 0 ;;
esac
exit 0
STUB
cat > "$stubs/skopeo" <<'STUB'
#!/usr/bin/bash
case "$STUB_MODE" in
    stale) echo "sha256:old" ;;
    *) echo "sha256:new" ;;
esac
STUB
chmod +x "$stubs"/*

run() { # run MODE TAG...
    local mode="$1"; shift
    : > "$stubs/log"
    STUB_MODE="$mode" STUB_LOG="$stubs/log" CI_PUSH_RETRY_SLEEP=0 PATH="$stubs:$PATH" \
        bash build/ci-push.sh ghcr.io/example/img "$@"
}
attempts() { grep -c push "$stubs/log"; }
export -f run
export stubs

check bash -c '! run fail 44-x >/dev/null 2>&1'
check bash -c 'run fail 44-x 2>&1 | grep -q "failed after 3 attempts"'
run fail 44-x >/dev/null 2>&1; check test "$(attempts)" = 3
check bash -c 'run ok 44-x | grep -qx "44-x sha256:new"'
check bash -c 'run flaky 44-x >/dev/null'
run flaky 44-x >/dev/null 2>&1; check test "$(attempts)" = 3
check bash -c '! run stale 44-x >/dev/null 2>&1'
check bash -c 'run stale 44-x 2>&1 | grep -q "digest mismatch"'
check bash -c 'run ok 44 latest | grep -c sha256:new | grep -qx 2'
check bash -c '! run ok >/dev/null 2>&1'
check bash -c 'run ok 2>&1 | grep -q "no tags"'

exit "$fail"
