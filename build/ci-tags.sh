#!/usr/bin/bash
# Usage: ci-tags.sh EVENT REF VERSION
# Prints the tags CI pushes, one per line. pull_request pushes nothing.
# main (push, nightly, dispatch) gets the release tags; any other branch gets
# a single dev-<branch> tag so a branch can be tried on the VM before merging.
# Anything else (a dispatch on a tag) is an error, not a dev-refs-tags-* tag.
set -euo pipefail
event="${1:?event}"; ref="${2:?ref}"; version="${3:?version}"

[ "$event" = pull_request ] && exit 0

if [ "$ref" = refs/heads/main ]; then
    # Unique tag first: CI pushes and signs it before re-pointing 44/latest.
    printf '%s\n' "44-${version}" 44 latest
elif [[ "$ref" == refs/heads/?* ]]; then
    branch="${ref#refs/heads/}"
    printf 'dev-%s\n' "${branch//\//-}"
else
    echo "ci-tags.sh: not a branch ref: $ref" >&2
    exit 1
fi
