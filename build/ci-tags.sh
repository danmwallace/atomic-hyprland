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
