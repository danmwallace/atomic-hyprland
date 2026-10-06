set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := false

image   := "ghcr.io/danmwallace/atomic-hyprland"
tag     := "44"
# CI passes IMAGE_VERSION so the label, the tag and the stamp agree; locally it
# is computed, with -dirty when the tree has uncommitted changes.
version := env("IMAGE_VERSION", `date -u +%Y%m%d` + "-" + `git rev-parse --short HEAD` + `test -z "$(git status --porcelain)" || echo -dirty`)

# Build the image locally (rootless podman). THEME: nord | tokyo-night | monochrome
build theme="nord" nvidia="0":
    source build/images.env && podman build \
        --build-arg BASE_IMAGE="$BASE_IMAGE" \
        --build-arg THEME={{theme}} \
        --build-arg NVIDIA={{nvidia}} \
        --build-arg IMAGE_VERSION={{version}} \
        -t {{image}}:{{tag}} -t {{image}}:{{tag}}-{{version}} .

# Host-side CI helper tests, then the in-image smoke + dotfile sync tests
test:
    bash tests/test-ci-tags.sh
    bash tests/test-justfile.sh
    podman run --rm -e PUBKEY_SHA256="$(sha256sum cosign.pub | cut -d' ' -f1)" \
        -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/image-smoke.sh
    podman run --rm -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/test-sync-dotfiles.sh

# bootc's own lint, standalone
lint:
    podman run --rm {{image}}:{{tag}} bootc container lint

# Base and akmods must be built for the same kernel
check-kernel:
    build/check-kernel-match.sh

# Sign the pushed image by digest and verify the signature. Signing by digest
# covers every tag pointing at it. The two =false flags produce the legacy
# simple-signing payload, the only format bootc/podman/skopeo verify today.
# Needs cosign 3.1.3 and COSIGN_PRIVATE_KEY in the environment (CI secret).
sign tag=tag:
    test -n "${COSIGN_PRIVATE_KEY:-}" || { echo "COSIGN_PRIVATE_KEY is not set" >&2; exit 1; }
    digest="$(skopeo inspect docker://{{image}}:{{tag}} --format '{{{{.Digest}}')" && \
        cosign sign -y --new-bundle-format=false --use-signing-config=false \
            --key env://COSIGN_PRIVATE_KEY "{{image}}@${digest}" && \
        cosign verify --new-bundle-format=false --key cosign.pub "{{image}}@${digest}"

# bootc-image-builder needs root podman (loop devices) and reads the image from
# root's container store, hence the sudo podman pull first.

# Build output/qcow2/disk.qcow2 from the pushed image (sudo)
qcow2:
    mkdir -p output
    sudo podman pull {{image}}:{{tag}}
    sudo podman run --rm -it --privileged --security-opt label=type:unconfined_t \
        -v ./output:/output \
        -v /var/lib/containers/storage:/var/lib/containers/storage \
        quay.io/centos-bootc/bootc-image-builder:latest \
        build --type qcow2 --rootfs btrfs --chown "$(id -u):$(id -g)" {{image}}:{{tag}}
    ls -lh output/qcow2/disk.qcow2

# Lint the workflow (actionlint) via podman; nothing installed locally
lint-ci:
    podman run --rm -v .:/repo:ro,Z -w /repo docker.io/rhysd/actionlint:latest -color
    podman run --rm -v ./renovate.json:/usr/src/app/renovate.json:ro,Z \
        docker.io/renovate/renovate:latest renovate-config-validator --strict
