#!/usr/bin/bash
# Third-party apps Dan approved (2026-11-08), each pinned in the Containerfile:
#   Orca (stablyai/orca, MIT)              upstream RPM, version + sha256
#   spotify_player (aome510, MIT)          upstream tarball, version + sha256
#   Tailscale                              pkgs.tailscale.com repo (repo_gpgcheck),
#                                          enabled for the build only (90-cleanup)
# Renovate proposes the version bumps; the hashes are updated by hand in the
# same PR, so a replaced or tampered release asset fails the build.
set -euo pipefail
orca_version="${1:?orca version}"
orca_sha256="${2:?orca sha256}"
spotify_player_version="${3:?spotify_player version}"
spotify_player_sha256="${4:?spotify_player sha256}"

work=/tmp/build/apps
mkdir -p "${work}"

# --- Tailscale -------------------------------------------------------------
curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 -o /etc/yum.repos.d/tailscale.repo https://pkgs.tailscale.com/stable/fedora/tailscale.repo
dnf -y install --setopt=install_weak_deps=False tailscale

# --- Orca ------------------------------------------------------------------
# electron-builder RPMs install under /opt/<Product>. On bootc /opt is a link
# into /var, which is never part of the image, so install into a real /opt for
# the duration and move the app into /usr. The app and its CLI shim resolve
# their paths relative to themselves; only the launcher, the /usr/bin link and
# chrome-sandbox's setuid bit (set by the RPM scriptlet) need adjusting.
orca_rpm="orca-ide-${orca_version}.x86_64.rpm"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 -o "${work}/${orca_rpm}" "https://github.com/stablyai/orca/releases/download/v${orca_version}/orca-ide-${orca_version}.x86_64.rpm"
( cd "${work}" && echo "${orca_sha256}  ${orca_rpm}" | sha256sum -c - )
rm /opt && mkdir /opt
dnf -y install --setopt=install_weak_deps=False "${work}/${orca_rpm}"
mv /opt/Orca /usr/lib/Orca
rmdir /opt && ln -s var/opt /opt
chmod 4755 /usr/lib/Orca/chrome-sandbox
ln -sfn /usr/lib/Orca/resources/bin/orca-ide /usr/bin/orca-ide
sed -i 's|^Exec=/opt/Orca/orca-ide|Exec=/usr/lib/Orca/orca-ide|' /usr/share/applications/orca-ide.desktop

# --- spotify_player --------------------------------------------------------
sp_tar="spotify_player-x86_64-unknown-linux-gnu.tar.gz"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 -o "${work}/${sp_tar}" "https://github.com/aome510/spotify-player/releases/download/v${spotify_player_version}/${sp_tar}"
( cd "${work}" && echo "${spotify_player_sha256}  ${sp_tar}" | sha256sum -c - )
tar -xzf "${work}/${sp_tar}" -C "${work}" spotify_player
install -m 0755 "${work}/spotify_player" /usr/bin/spotify_player
