#!/usr/bin/bash
# Phase 1: let bootc pull our own image unsigned. Phase 3 replaces this entry
# with sigstoreSigned. The ublue base ships default=reject, so without an
# entry `bootc upgrade` would refuse ghcr.io/danmwallace/atomic-hyprland.
set -euo pipefail
policy=/etc/containers/policy.json
tmp="$(mktemp)"
jq '.transports.docker["ghcr.io/danmwallace/atomic-hyprland"] = [{"type": "insecureAcceptAnything"}]' "${policy}" > "${tmp}"
install -m 0644 "${tmp}" "${policy}"
rm -f "${tmp}"
