#!/usr/bin/bash
# Usage: ci-push.sh IMAGE TAG...
# Pushes the local IMAGE:44 under each TAG with retries, then proves each tag
# landed by comparing the registry's digest with the one podman reported.
# A retry loop alone would swallow a final failure, and a bare inspect would
# be satisfied by whatever the tag pointed at before; the comparison is what
# fails the step. CI_PUSH_RETRY_SLEEP (seconds, default 10) scales both the
# push retries and the registry polling (10+20+30+40 s at most); tests set 0.
set -euo pipefail
image="${1:?image}"; shift
[ $# -ge 1 ] || { echo "no tags to push" >&2; exit 1; }
: "${CI_PUSH_RETRY_SLEEP:=10}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for tag in "$@"; do
    podman tag "${image}:44" "${image}:${tag}"
    pushed=0
    for i in 1 2 3; do
        if podman push --digestfile "${tmp}/digest" "${image}:${tag}"; then
            pushed=1
            break
        fi
        sleep $((CI_PUSH_RETRY_SLEEP * i))
    done
    [ "$pushed" = 1 ] || { echo "push of ${image}:${tag} failed after 3 attempts" >&2; exit 1; }
    want="$(cat "${tmp}/digest")"
    # ghcr can answer "manifest unknown", or the tag's previous digest, for a
    # moment after the push that moved it, so the check polls before failing.
    got=""
    for i in 1 2 3 4 5; do
        got="$(skopeo inspect "docker://${image}:${tag}" --format '{{.Digest}}' 2>/dev/null)" || got=""
        [ "$got" = "$want" ] && break
        [ "$i" = 5 ] || sleep $((CI_PUSH_RETRY_SLEEP * i))
    done
    [ -n "$got" ] || { echo "${image}:${tag} not visible in the registry after the push" >&2; exit 1; }
    [ "$got" = "$want" ] || { echo "digest mismatch for ${tag}: registry ${got}, pushed ${want}" >&2; exit 1; }
    echo "${tag} ${got}"
done
