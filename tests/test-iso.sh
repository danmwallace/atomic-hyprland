#!/usr/bin/bash
# Host-side: bash tests/test-iso.sh [ISO | DIR-with-osbuild*.ks]
# The installer ISO must be interactive: the user picks the disk, sets the LUKS
# passphrase and creates the user. bootc-image-builder writes clearpart --all /
# autopart / reboot into its kickstart unless we supply our own, so this checks
# both our config and (when given) the kickstarts inside the built ISO.
set -uo pipefail
fail=0
check() { if "$@" >/dev/null 2>&1; then echo "ok    $*"; else echo "FAIL  $*"; fail=1; fi; }

cfg=build/iso.toml
signed='bootc switch --mutate-in-place --enforce-container-sigpolicy --transport registry ghcr.io/danmwallace/atomic-hyprland:44'
check test -f "$cfg"
check grep -qx '\[customizations.installer.kickstart\]' "$cfg"
check grep -qF "$signed" "$cfg"
check grep -q '^%post --erroronfail$' "$cfg"
# only what BIB reads: comment lines are free to explain the danger
for bad in clearpart zerombr autopart reboot rootpw unattended ignoredisk; do
    check bash -c "! grep -vE '^\s*#' '$cfg' | grep -qiE '(^|[^a-z])${bad}'"
done

if [[ -n "${1:-}" ]]; then
    src="$1"; dir="$src"
    if [[ -f "$src" ]]; then
        dir="$(mktemp -d)"
        # Any ISO reader will do; frmwrk has 7z but not xorriso. With none, say so
        # rather than reporting the kickstarts as missing.
        if command -v xorriso >/dev/null; then
            for ks in osbuild.ks osbuild-base.ks; do
                xorriso -osirrox on -indev "$src" -extract "/$ks" "$dir/$ks" >/dev/null 2>&1 || true
            done
        elif command -v 7z >/dev/null; then
            7z e -o"$dir" "$src" 'osbuild*.ks' >/dev/null 2>&1 || true
        elif command -v bsdtar >/dev/null; then
            bsdtar -xf "$src" -C "$dir" 'osbuild*.ks' >/dev/null 2>&1 || true
        else
            echo "FAIL  no ISO reader: install xorriso (sudo dnf install xorriso) or 7z"
            fail=1
        fi
    fi
    check test -s "$dir/osbuild.ks"
    for bad in clearpart zerombr autopart 'reboot' 'rootpw'; do
        check bash -c "! cat '$dir'/osbuild*.ks | grep -qE '^${bad}'"
    done
    check bash -c "cat '$dir'/osbuild*.ks | grep -q '^ostreecontainer '"
    # ours must run after BIB's own unverified switch, so the signed transport wins
    check bash -c "test \"\$(cat '$dir'/osbuild*.ks | grep -n 'bootc switch' | tail -1 | grep -c -- '--enforce-container-sigpolicy')\" = 1"
fi
# Regression fixtures: the kickstarts from the first (unattended) ISO must be rejected,
# the ones from the fixed ISO accepted. Runs only when called without an argument.
if [[ -z "${1:-}" ]]; then
    check bash -c '! bash tests/test-iso.sh tests/fixtures/iso-unattended'
    check bash tests/test-iso.sh tests/fixtures/iso-interactive
fi
exit "$fail"
