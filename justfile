set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := false

image   := "ghcr.io/danmwallace/atomic-hyprland"
tag     := "44"
version := `date -u +%Y%m%d` + "-" + `git rev-parse --short HEAD`

# Build the image locally (rootless podman). THEME: nord | tokyo-night | monochrome
build theme="nord" nvidia="0":
    source build/images.env && podman build \
        --build-arg BASE_IMAGE="$BASE_IMAGE" \
        --build-arg THEME={{theme}} \
        --build-arg NVIDIA={{nvidia}} \
        --build-arg IMAGE_VERSION={{version}} \
        -t {{image}}:{{tag}} -t {{image}}:{{tag}}-{{version}} .

# Run the in-image smoke tests
test:
    podman run --rm -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/image-smoke.sh
    podman run --rm -v ./tests:/tests:ro,Z {{image}}:{{tag}} bash /tests/test-sync-dotfiles.sh

# bootc's own lint, standalone
lint:
    podman run --rm {{image}}:{{tag}} bootc container lint

# Base and akmods must be built for the same kernel
check-kernel:
    build/check-kernel-match.sh

# Push both tags to ghcr.io (needs: gh auth token | podman login ghcr.io -u danmwallace --password-stdin)
push:
    podman tag {{image}}:{{tag}} {{image}}:{{tag}}-{{version}}
    podman push {{image}}:{{tag}}
    podman push {{image}}:{{tag}}-{{version}}

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
