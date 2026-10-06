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
