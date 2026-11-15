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
expect_fail() {
    # expect_fail DESC NEEDLE CMD...   CMD must exit non-zero and its stderr
    # must contain NEEDLE (a substring, so bash's "line N:" prefix may move)
    local desc="$1" needle="$2"
    shift 2
    local got rc=0
    got="$("$@" 2>&1 >/dev/null)" || rc=$?
    if [ "$rc" -ne 0 ] && [[ "$got" == *"$needle"* ]]; then
        echo "ok    $desc"
    else
        echo "FAIL  $desc"
        printf '  want: non-zero exit, stderr containing %q\n  got:  rc=%s %q\n' "$needle" "$rc" "$got"
        fail=1
    fi
}

s=build/ci-tags.sh
v=20261005-abc1234
expect "push to main"                  $'44-20261005-abc1234\n44\nlatest' "$s" push             refs/heads/main      "$v"
expect "nightly is main"               $'44-20261005-abc1234\n44\nlatest' "$s" schedule         refs/heads/main      "$v"
expect "dispatch from main"            $'44-20261005-abc1234\n44\nlatest' "$s" workflow_dispatch refs/heads/main     "$v"
expect "dispatch branch with slash"    "dev-dw-phase3"                     "$s" workflow_dispatch refs/heads/dw/phase3 "$v"
expect "dispatch plain branch"         "dev-fix-waybar"                    "$s" workflow_dispatch refs/heads/fix-waybar "$v"
expect "pull request prints nothing"   ""                                  "$s" pull_request     refs/pull/12/merge   "$v"
expect_fail "missing version is an error" "3: version"            "$s" push refs/heads/main
# workflow_dispatch can run on a tag; that is not a branch and gets no dev- tag
expect_fail "tag ref is rejected"         "not a branch ref: refs/tags/v1" "$s" workflow_dispatch refs/tags/v1 "$v"
expect      "tag ref prints no tags"      ""                                bash -c '"$0" "$@" 2>/dev/null; true' "$s" workflow_dispatch refs/tags/v1 "$v"

exit "$fail"
