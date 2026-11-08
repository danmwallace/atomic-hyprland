#!/usr/bin/bash
# Runs INSIDE the built image: podman run --rm -v ./tests:/tests:ro,Z IMAGE bash /tests/image-smoke.sh
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

check rpm -q hyprland hyprlock hypridle xdg-desktop-portal-hyprland
check rpm -q sddm sddm-x11 waybar wofi alacritty swaybg cliphist
check rpm -q elvish starship lazygit fzf ripgrep fd-find bat git gh jq yq uv distrobox
check rpm -q cloud-init qemu-guest-agent
# Ansible become_user to an unprivileged user (hermes) needs setfacl on the target.
check rpm -q acl
check bash -c '! rpm -q fish'
# The Hyprland config lives in this repo now; Ansible left the build with it.
check bash -c '! rpm -q ansible-core python3-libdnf5 hyprpaper nwg-drawer nwg-dock-hyprland qt6ct waypaper'
check rpm -q uwsm hyprland-uwsm file
check bash -c '! rpm -q librsvg2-tools'   # build-time only
for f in env input binds rules look monitors autostart; do check test -f /usr/share/atomic-hyprland/hypr/$f.lua; done
check bash -c '! grep -rq special_scale_factor /usr/share/atomic-hyprland /etc/skel'
check grep -q 'rounding = 3' /usr/share/atomic-hyprland/hypr/look.lua
check grep -q 'gaps_out = 8' /usr/share/atomic-hyprland/hypr/look.lua
check test -f /etc/skel/.config/hypr/hyprland.lua
check test -f /etc/skel/.config/hypr/local.lua
check bash -c '! test -e /etc/skel/.config/hypr/conf'
check bash -c '! test -e /etc/skel/.config/hypr/hyprland.conf'
check grep -q 'package.path = "/usr/share/atomic-hyprland/hypr/?.lua;"' /etc/skel/.config/hypr/hyprland.lua
check grep -q 'pcall(require, "local")' /etc/skel/.config/hypr/hyprland.lua
check test -f /usr/share/wayland-sessions/hyprland.desktop
for t in monochrome-green monochrome-blue tokyo-night nord dracula; do
    check test -f /usr/share/atomic-hyprland/themes/$t/colors.toml
    check test -f /usr/share/atomic-hyprland/themes/$t/backgrounds/00-plain.png
    check bash -c "file /usr/share/atomic-hyprland/themes/$t/backgrounds/00-plain.png | grep -q '3840 x 2160'"
done
check test -x /usr/bin/hypr-theme
# The quiet bar, notifications, wallpaper and idle daemon as session units.
check rpm -q mako libnotify
for u in waybar mako swaybg hypridle; do
    check test -f /usr/lib/systemd/user/$u.service
    check test -L /etc/systemd/user/graphical-session.target.wants/$u.service
done
check test -L /etc/systemd/user/graphical-session.target.wants/atomic-hyprland-battery.timer
check test -f /etc/skel/.config/waybar/config.jsonc
check bash -c '! test -e /etc/skel/.config/waybar/config'
check jq -e . /etc/skel/.config/waybar/config.jsonc
check test -L /etc/skel/.config/mako/config
check test "$(readlink /etc/skel/.config/mako/config)" = ../atomic-hyprland/current/theme/mako.ini
check test -x /usr/libexec/atomic-hyprland/waybar/gpu
check bash -c '/usr/libexec/atomic-hyprland/waybar/gpu | jq -e .text'
check bash -c '/usr/libexec/atomic-hyprland/waybar/notifications | jq -e .text'
check grep -qx .config/waybar/local.jsonc /usr/share/atomic-hyprland/skel.local
check bash -c '! grep -q local.jsonc /usr/share/atomic-hyprland/managed-files.txt'
check grep -qx .config/waybar/config /usr/share/atomic-hyprland/skel.retired
# Launcher, power menu, lock screen, terminals, btop
check rpm -q btop
check test -x /usr/bin/hypr-power
check bash -c '! rpm -q wlogout'
check test -f /etc/skel/.config/wofi/style.css
check bash -c '! test -e /etc/skel/.config/wofi/style-power.css'
check test -f /etc/skel/.config/ghostty/config
check test -f /etc/skel/.config/alacritty/alacritty.toml
check test -L /etc/skel/.config/btop/themes/current.theme
check grep -q 'source = ~/.config/atomic-hyprland/current/theme/hyprlock.conf' /etc/skel/.config/hypr/hyprlock.conf
check bash -c '! grep -rq earth_from_space /etc/skel /usr/share/atomic-hyprland'
# GTK, Qt, Flatpak, icons, cursor, fonts
check rpm -q papirus-icon-theme papirus-icon-theme-dark breeze-cursor-theme kvantum kvantum-qt5 gsettings-desktop-schemas dconf rsms-inter-fonts google-noto-color-emoji-fonts flatpak
check bash -c 'fc-match "JetBrainsMono Nerd Font" | grep -q JetBrainsMono'
check bash -c 'fc-match monospace | grep -q JetBrainsMono'
check bash -c '! fc-list | grep -q RobotoMono'
check test -d /usr/share/icons/Papirus-Dark
check test -d /usr/share/icons/breeze_cursors
check test -d /usr/share/Kvantum/KvGnomeDark
check test "$(readlink /etc/skel/.config/gtk-4.0/gtk.css)" = ../atomic-hyprland/current/theme/gtk.css
check grep -q 'QT_STYLE_OVERRIDE", "kvantum"' /usr/share/atomic-hyprland/hypr/env.lua
check bash -c '! grep -q qt6ct /usr/share/atomic-hyprland/hypr/env.lua'
check grep -q JetBrainsMono /etc/fonts/local.conf
check bash -c 'gsettings list-schemas | grep -qx org.gnome.desktop.interface'
# SDDM greeter: our theme, coloured from the default palette at build, no virtual keyboard
check test -f /usr/share/sddm/themes/atomic-hyprland/Main.qml
check test -f /usr/share/sddm/themes/atomic-hyprland/metadata.desktop
check test -f /usr/share/sddm/themes/atomic-hyprland/theme.conf
check grep -qx 'background=/usr/share/atomic-hyprland/themes/monochrome-green/backgrounds/00-plain.png' /usr/share/sddm/themes/atomic-hyprland/theme.conf
check grep -qx 'accent=#39ff14' /usr/share/sddm/themes/atomic-hyprland/theme.conf
check bash -c '! grep -q "{{" /usr/share/sddm/themes/atomic-hyprland/theme.conf'
check grep -qx 'Current=atomic-hyprland' /etc/sddm.conf.d/10-atomic-hyprland.conf
check grep -qx 'InputMethod=' /etc/sddm.conf.d/10-atomic-hyprland.conf
check grep -qx 'DefaultSession=hyprland-uwsm.desktop' /etc/sddm.conf.d/10-atomic-hyprland.conf
check bash -c '! grep -rq abstractdark /etc/sddm.conf.d /usr/share/atomic-hyprland'
check bash -c '! grep -q VirtualKeyboard /usr/share/sddm/themes/atomic-hyprland/Main.qml'
check bash -c '! test -e /etc/sddm.conf.d/10-theme.conf'
check test -f /usr/share/wayland-sessions/hyprland-uwsm.desktop
# Chromium with the Claude extension (managed policy); Firefox is a Flatpak concern of the control repo
check rpm -q chromium
check test -x /usr/bin/chromium-browser
check jq -e '.ExtensionInstallForcelist | length == 1' /etc/chromium/policies/managed/10-atomic-hyprland.json
check test -f /usr/lib/systemd/user/atomic-hyprland-theme@.service
check test -L /etc/systemd/user/wayland-session-pre@.target.wants/atomic-hyprland-theme@.service
check bash -c '! test -e /usr/lib/systemd/user/atomic-hyprland-theme.service'
# symlinks in skel are image-managed too (mako config, gtk.css, btop theme)
check grep -qx .config/mako/config /usr/share/atomic-hyprland/managed-files.txt
check grep -qx .config/gtk-4.0/gtk.css /usr/share/atomic-hyprland/managed-files.txt
check grep -qx .config/btop/themes/current.theme /usr/share/atomic-hyprland/managed-files.txt
# Hyprland's own parser on the skel tree plus a rendered theme, without --config so
# its file selection picks hyprland.lua.
# verify_hypr [binds-line] [look-line] [theme]: copies the skel tree, renders the
# theme into the throwaway HOME (skipped with HV_NO_THEME=1 to exercise the
# built-in fallback palette), optionally adds a line as an extra module, wraps
# hl.config with a probe (tests/hypr-probe-pre.lua) that records every dotted
# config key and checks each with hl.get_config at the end
# (tests/hypr-probe-post.lua), because --verify-config alone ignores unknown keys.
verify_hypr() {
    export HOME=/tmp/hv XDG_RUNTIME_DIR=/tmp/hv/run
    rm -rf /tmp/hv; mkdir -p "$HOME/.config" "$XDG_RUNTIME_DIR"
    cp -a /etc/skel/.config/. "$HOME/.config/"   # the whole skel, as a first login gets it
    if [ -z "${HV_NO_THEME:-}" ]; then
        HYPR_THEME_SHARE=/usr/share/atomic-hyprland HYPR_THEME_STATE="$HOME/.config/atomic-hyprland" \
            HYPR_THEME_NO_APPLY=1 hypr-theme set "${3:-monochrome-green}" >/dev/null
    fi
    cp /tests/hypr-probe-pre.lua "$HOME/.config/hypr/probe_pre.lua"
    cp /tests/hypr-probe-post.lua "$HOME/.config/hypr/probe_post.lua"
    sed -i '1i require("probe_pre")' "$HOME/.config/hypr/hyprland.lua"
    [ -n "${1:-}" ] && { echo "$1" > "$HOME/.config/hypr/extra_binds.lua"; echo 'require("extra_binds")' >> "$HOME/.config/hypr/hyprland.lua"; }
    [ -n "${2:-}" ] && { echo "$2" > "$HOME/.config/hypr/extra_look.lua"; echo 'require("extra_look")' >> "$HOME/.config/hypr/hyprland.lua"; }
    echo 'require("probe_post")' >> "$HOME/.config/hypr/hyprland.lua"
    # Run as an unprivileged user, like a real session. Hyprland 0.57 in
    # verify mode has no instance directory and binds its event socket at
    # /.socket2.sock; as root that bind succeeds and it segfaults (exit 139)
    # before printing a verdict, as a user the bind is refused and it carries
    # on. VERIFY_EXIT makes a crash show up as a crash, not a missing string.
    chown -R nobody:nobody "$HOME"; chmod 700 "$XDG_RUNTIME_DIR"
    setpriv --reuid=nobody --regid=nobody --clear-groups Hyprland --verify-config 2>&1 \
        | sed 's/\x1b\[[0-9;]*m//g'
    echo "VERIFY_EXIT=${PIPESTATUS[0]}"
}
# expect_out <label> <present|absent> <regex>  (matches against $out)
expect_out() {
    local hit=1; grep -Eq "$3" <<< "$out" && hit=0
    if { [ "$2" = present ] && [ $hit = 0 ]; } || { [ "$2" = absent ] && [ $hit = 1 ]; }; then
        echo "ok    $1"
    else
        echo "FAIL  $1"; fail=1
    fi
}
for t in monochrome-green monochrome-blue tokyo-night nord dracula; do
    out="$(verify_hypr '' '' "$t")"
    expect_out "hyprland verify-config exits 0 for $t" present '^VERIFY_EXIT=0$'
    expect_out "hyprland reports config ok for $t" present 'config ok'
    expect_out "no Lua or config errors for $t" absent 'attempt to|stack traceback|Config error'
    expect_out "no unresolved placeholder for $t" absent '\{\{'
done
out="$(verify_hypr)"
# The render that verify_hypr just did must have produced every app's theme file.
check grep -q "@define-color accent #39ff14;" /tmp/hv/.config/atomic-hyprland/current/theme/waybar.css
check grep -q "^border-color=#39ff14" /tmp/hv/.config/atomic-hyprland/current/theme/mako.ini
# mako parses the rendered config (it only fails later, on the missing display/bus)
check bash -c '! HOME=/tmp/hv mako --config /tmp/hv/.config/atomic-hyprland/current/theme/mako.ini 2>&1 | grep -q "Failed to parse"'
check test -L /tmp/hv/.config/atomic-hyprland/current/background
for f in wofi.css hyprlock.conf ghostty.conf alacritty.toml btop.theme hyprland.lua gtk.css; do
    check test -s /tmp/hv/.config/atomic-hyprland/current/theme/$f
done
# 0.56 printed "Using lua config"; 0.57 prints "Regular config at <path>/hyprland.lua".
expect_out "hyprland picked the Lua config" present 'Using lua config|Regular config at .*/hyprland\.lua'
expect_out "every hl.config key is known to this Hyprland" present 'PROBE config keys ok'
expect_out "no unknown config keys in the shipped config" absent 'PROBE unknown config key'
# The theme file is missing (fresh home before ensure-theme ran): the built-in fallback palette must carry the config.
out="$(HV_NO_THEME=1 verify_hypr)"
expect_out "hyprland verifies with the built-in fallback palette" present '^VERIFY_EXIT=0$'
expect_out "fallback palette reports config ok" present 'config ok'
# Test of the test: an unknown key must be caught, since --verify-config alone accepts it.
out="$(verify_hypr '' 'hl.config({ general = { bogus_key_for_probe = 1 } })')"
expect_out "an unknown hl.config key is detected by the probe" present 'PROBE unknown config key: general.bogus_key_for_probe'
# Error isolation: a broken module must be reported by name while the entry file still loads.
out="$(verify_hypr 'hl.bind("SUPER + Z", hl.dsp.nonexistent())')"
expect_out "broken module is reported by name" present 'extra_binds.lua'
expect_out "broken module does not fail hyprland.lua" absent 'hyprland.lua:'
check rpm -q hyprland-guiutils
# Extra terminals: Ghostty from the scottames/ghostty COPR; tuios is not
# packaged for Fedora, so it is upstream's release binary under /usr/bin.
check rpm -q ghostty
check bash -c 'ghostty +version | grep -qi "^ghostty "'
check test -x /usr/bin/tuios
check bash -c 'tuios --version 2>&1 | grep -Eq "[0-9]+\.[0-9]+\.[0-9]+"'
check test -f /usr/share/licenses/tuios/LICENSE
check bash -c '! grep -q "custom/updates" /etc/skel/.config/waybar/config'
check test -L /etc/systemd/system/display-manager.service
check test "$(readlink -f /etc/systemd/system/default.target)" = /usr/lib/systemd/system/graphical.target
check grep -q '^/usr/bin/elvish$' /etc/shells
# Phase 3: trust policy. Our scope demands a cosign signature; the base's
# catch-all "" docker scope must survive, it is what lets the Ollama image pull.
policy=/etc/containers/policy.json
scope='.transports.docker["ghcr.io/danmwallace/atomic-hyprland"]'
check jq -e "${scope} | length == 1" "$policy"
check jq -e "${scope}[0].type == \"sigstoreSigned\"" "$policy"
check jq -e "${scope}[0].keyPaths | type == \"array\" and length >= 1" "$policy"
check jq -e "${scope}[0].signedIdentity.type == \"matchRepository\"" "$policy"
check jq -e '.transports.docker[""][0].type == "insecureAcceptAnything"' "$policy"
for key in $(jq -r "${scope}[0].keyPaths[]? // empty" "$policy"); do
    check test -f "$key"
    check test "$(stat -c %a "$key")" = 644
    check openssl pkey -pubin -in "$key" -noout
done
# The key in the image must be the key in the repo; just test passes the sha.
check test "$(sha256sum /etc/pki/containers/atomic-hyprland.pub 2>/dev/null | cut -d' ' -f1)" = "${PUBKEY_SHA256:?set by just test}"
reg=/etc/containers/registries.d/atomic-hyprland.yaml
check test -f "$reg"
check bash -c "yq -e '.docker[\"ghcr.io/danmwallace/atomic-hyprland\"][\"use-sigstore-attachments\"] == true' $reg"
check bash -c "test \"\$(yq '.docker | keys | length' $reg)\" = 1"
# Only the COPRs this build enables (new-style file names); the ublue base ships
# its own _copr_ublue-os-akmods.repo enabled and that is left as-is.
check bash -c '! grep -ls "^enabled=1" /etc/yum.repos.d/_copr:copr.fedorainfracloud.org:*.repo'
check test -s /usr/share/atomic-hyprland/stamp
check test -f /usr/share/atomic-hyprland/skel/.config/hypr/hyprland.lua
check test -f /usr/share/atomic-hyprland/skel.local
check test -f /usr/share/atomic-hyprland/skel.retired
check bash -c '! grep -qx .config/hypr/local.lua /usr/share/atomic-hyprland/managed-files.txt'
check bash -c '! test -e /var/roothome/.ansible'
check bash -c 'test -z "$(ls -A /var/cache 2>/dev/null)"'

# Phase 2: AI service Quadlets, Claude Code, GUI apps as Flatpaks
check test -f /usr/share/containers/systemd/ai.network
check test -f /usr/share/containers/systemd/ollama.container
# LiteLLM was dropped 2026-11-07 (OpenRouter covers the hosted-model use); nothing may bring it back.
check test ! -e /usr/share/containers/systemd/litellm.container
out="$(/usr/lib/systemd/system-generators/podman-system-generator --dryrun 2>&1)"
expect_out "quadlet generator renders ollama.service" present 'ollama.service'
expect_out "quadlet generator renders no litellm.service" absent 'litellm.service'
expect_out "quadlet generator renders ai-network.service" present 'ai-network.service'
expect_out "quadlet generator reports no errors" absent '[Ee]rror'
# First boot: images are pulled by a oneshot without podman's 5-minute in-systemd cap.
check test -f /usr/lib/systemd/system/ai-images-pull.service
check test -L /etc/systemd/system/multi-user.target.wants/ai-images-pull.service
check grep -q 'TimeoutStartSec=0' /usr/lib/systemd/system/ai-images-pull.service
# Later boots must not touch the registry (offline boot must not fail the unit).
check bash -c 'grep -c "podman image exists" /usr/lib/systemd/system/ai-images-pull.service | grep -qx 1'
check bash -c '! grep -q litellm /usr/lib/systemd/system/ai-images-pull.service'
check grep -q 'After=.*ai-images-pull.service' /usr/share/containers/systemd/ollama.container
# podman does not create a missing bind-mount source; tmpfiles makes /var/lib/ollama at boot.
check grep -qE '^d /var/lib/ollama ' /usr/lib/tmpfiles.d/atomic-hyprland.conf
check bash -c 'claude --version | grep -q "^2\.1\.289"'
check bash -c '! rpm -q firefox'
check bash -c '! rpm -q libreoffice-core'
check bash -c '! rpm -q thunderbird'

# Phase 3: stage-only updates. One updater (bootc), staged, never auto-rebooted.
check test "$(systemctl is-enabled bootc-fetch-apply-updates.timer 2>/dev/null)" = enabled
check test "$(systemctl is-enabled rpm-ostreed-automatic.timer 2>/dev/null)" = disabled
dropin=/usr/lib/systemd/system/bootc-fetch-apply-updates.service.d/stage-only.conf
check test -f "$dropin"
check test "$(stat -c %a "$dropin" 2>/dev/null)" = 644
# The drop-in must reset ExecStart and set the stage-only command.
check grep -qx 'ExecStart=' "$dropin"
check grep -qx 'ExecStart=/usr/bin/bootc upgrade --quiet' "$dropin"
check bash -c '! grep -E "^ExecStart=" '"$dropin"' | grep -q -- --apply'
# systemctl cat lists the drop-in only if the directory name matches the unit.
check bash -c 'systemctl cat bootc-fetch-apply-updates.service | grep -q stage-only.conf'

# Phase 4: NVIDIA layer (present on every machine; inert without the hardware)
check rpm -q kmod-nvidia nvidia-driver nvidia-driver-cuda nvidia-container-toolkit egl-wayland libva-nvidia-driver ublue-os-nvidia-addons
check test "$(rpm -q --qf '%{VERSION}' kmod-nvidia)" = "$(rpm -q --qf '%{VERSION}' nvidia-driver)"
kver="$(rpm -q --qf '%{evr}.%{arch}' kernel-core)"
check test "$(ls /usr/lib/modules | wc -l)" = 1
check bash -c "find /usr/lib/modules/${kver} -name 'nvidia.ko*' | grep -q ."
# The kmod package installs under the image's own kernel directory.
check bash -c "rpm -ql kmod-nvidia | grep -q \"/${kver}/\""
check bash -c '! rpm -qa | grep -E "nvidia.*\.i686"'
check bash -c "lsinitrd /usr/lib/modules/${kver}/initramfs.img | grep -q 'nvidia.ko'"
check bash -c 'nvidia-ctk --version | grep -qi "version"'
check test "$(systemctl is-enabled nvidia-cdi-refresh.path 2>/dev/null)" = enabled
check test "$(systemctl is-enabled nvidia-persistenced.service 2>/dev/null)" = enabled
check bash -c '! dnf5 repolist --enabled 2>/dev/null | grep -qi nvidia'
check bash -c '! ls /usr/share/vulkan/icd.d/nouveau_icd.*.json 2>/dev/null | grep -q .'

kargs=/usr/lib/bootc/kargs.d/00-nvidia.toml
check test -f "$kargs"
check python3 -c "import tomllib,sys; k=tomllib.load(open('$kargs','rb'))['kargs']; sys.exit(0 if k==['rd.driver.blacklist=nouveau','modprobe.blacklist=nouveau','nvidia-drm.modeset=1'] else 1)"
# Both units the installer enables fail without the hardware; a condition makes
# them skip cleanly, since this one image also boots on GPU-less machines.
for u in nvidia-persistenced nvidia-cdi-refresh; do
    d="/usr/lib/systemd/system/${u}.service.d/10-require-gpu.conf"
    check test -f "$d"
    check grep -qx 'ConditionPathExists=/proc/driver/nvidia/version' "$d"
    check bash -c "systemctl cat ${u}.service | grep -q 10-require-gpu.conf"
done
# GPU for Ollama is switched on per host by the playbook, never in the image.
check bash -c '! grep -rq "AddDevice" /usr/share/containers/systemd/'

exit "$fail"
