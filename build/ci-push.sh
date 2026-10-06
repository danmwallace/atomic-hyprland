#!/usr/bin/bash
# Usage: ci-push.sh IMAGE TAG...
# Pushes the local IMAGE:44 under each TAG with retries, then proves each tag
# landed by comparing the registry's digest with the one podman reported.
# A retry loop alone would swallow a final failure, and a bare inspect would
# be satisfied by whatever the tag pointed at before; the comparison is what
# fails the step. CI_PUSH_RETRY_SLEEP (seconds, default 10) exists for tests.
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
    got="$(skopeo inspect "docker://${image}:${tag}" --format '{{.Digest}}')"
    [ "$got" = "$want" ] || { echo "digest mismatch for ${tag}: registry ${got}, pushed ${want}" >&2; exit 1; }
    echo "${tag} ${got}"
done
