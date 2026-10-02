#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
sdk="$1"
shift
image="holoscan-telesurgery:sdk$sdk"
if ! command -v docker >/dev/null; then
    echo "Install Docker and NVIDIA Container Toolkit first." >&2
    exit 1
fi
if [[ "${1:-}" == patient || "${1:-}" == surgeon || "${1:-}" == node ]] &&
    ! command -v chronyc >/dev/null &&
    ! systemctl is-enabled --quiet ptp4l phc2sys ntp ntpsec 2>/dev/null; then
    "$root/setup.sh" --docker --sdk "$sdk"
fi
build_args=(--build-arg "SDK=$sdk")
own_agent=false
cleanup() {
    if $own_agent; then ssh-agent -k >/dev/null; fi
}
trap cleanup EXIT
if grep -Eq 'git[[:space:]]*=[[:space:]]*"(ssh://|[^/"]+@)' "$root/dependencies/sdk$sdk.toml"; then
    if [[ ! -S "${SSH_AUTH_SOCK:-}" ]]; then
        eval "$(ssh-agent -s)" >/dev/null
        own_agent=true
    fi
    if ! ssh-add -l >/dev/null 2>&1; then ssh-add; fi
    build_args+=(--ssh default)
fi
if [[ -f "$HOME/.ssh/known_hosts" ]]; then
    build_args+=(--secret "id=known_hosts,src=$HOME/.ssh/known_hosts")
fi
if [[ -f "$HOME/.ssh/config" ]]; then
    build_args+=(--secret "id=ssh_config,src=$HOME/.ssh/config")
fi
docker build "${build_args[@]}" --tag "$image" "$root"
mkdir -p "$root/runs"
if [[ ( "${1:-}" == patient || "${1:-}" == node ) && ! -d "$root/runs/sim-deps" ]]; then
    docker run --rm --user "$(id -u):$(id -g)" --volume "$root/runs:/runs" \
        --entrypoint cp "$image" -r /opt/sim-deps /runs/sim-deps
fi
args=(--rm --init --gpus all --network host --user "$(id -u):$(id -g)"
      --ulimit stack=33554432 --ulimit memlock=-1
      --env XDG_CACHE_HOME=/tmp/cache --env CUPY_CACHE_DIR=/tmp/cupy
      --env "TELESURGERY_WORKSPACE=$root" --env "HOME=$HOME"
      --volume /etc/passwd:/etc/passwd:ro --volume /etc/group:/etc/group:ro
      --volume "$root:$root:ro" --volume "$root/runs:$root/runs" --workdir "$root")
if [[ -t 0 && -t 1 ]]; then args+=(-it); fi
for device in /dev/video*; do
    if [[ -e "$device" ]]; then
        args+=(--device "$device" --group-add "$(stat -c %g "$device")")
    fi
done
if [[ -d /dev/v4l ]]; then args+=(--volume /dev/v4l:/dev/v4l:ro); fi
if [[ -n "${DISPLAY:-}" && -d /tmp/.X11-unix ]]; then
    args+=(--env DISPLAY --volume /tmp/.X11-unix:/tmp/.X11-unix:ro)
    display_auth="${XAUTHORITY:-$HOME/.Xauthority}"
    if [[ -f "$display_auth" ]]; then
        args+=(--env XAUTHORITY=/tmp/telesurgery-xauthority
               --volume "$display_auth:/tmp/telesurgery-xauthority:ro")
    fi
fi
# Simulation uses the host Docker service; SSH enrollment uses the host credentials.
if [[ "${1:-}" == patient || "${1:-}" == node ]]; then
    args+=(--volume /var/run/docker.sock:/var/run/docker.sock --group-add "$(stat -c %g /var/run/docker.sock)")
fi
if [[ "${1:-}" == patient ]]; then
    if [[ -d "$HOME/.ssh" ]]; then args+=(--volume "$HOME/.ssh:$HOME/.ssh:ro"); fi
    if [[ -S "${SSH_AUTH_SOCK:-}" ]]; then
        args+=(--env SSH_AUTH_SOCK=/tmp/ssh-agent --volume "$SSH_AUTH_SOCK:/tmp/ssh-agent")
    fi
fi
docker run "${args[@]}" "$image" "$@"
