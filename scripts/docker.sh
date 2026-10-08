#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
sdk="$1"
shift
image="holoscan-telesurgery:sdk$sdk"
workspace="$root/workspace"
app_args=("$@")
mounts=()
simulation=false
for ((i=0; i<${#app_args[@]}; i++)); do
    option="${app_args[i]%%=*}"
    case "$option" in
        --workspace|--ssl-cert|--ssl-key)
            index=$i
            if [[ "${app_args[i]}" == *=* ]]; then
                path="${app_args[i]#*=}"
            else
                ((i+=1))
                path="${app_args[i]:?path option requires a value}"
            fi
            if [[ "$option" == --workspace ]]; then
                workspace="$(realpath -m -- "$path")"
                path="$workspace"
            else
                path="$(realpath -e -- "$path")"
                mounts+=(--volume "$path:$path:ro")
            fi
            if [[ "$index" == "$i" ]]; then
                app_args[i]="$option=$path"
            else
                app_args[i]="$path"
            fi ;;
        --sim) simulation=true ;;
    esac
done
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
if [[ -n "${CUDAARCHS:-}" ]]; then build_args+=(--build-arg "CUDAARCHS=$CUDAARCHS"); fi
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
mkdir -p "$workspace"
if [[ "${1:-}" == node ]] && $simulation; then
    mkdir -p "$workspace/sim-deps"
    docker run --rm --user "$(id -u):$(id -g)" --volume "$workspace:/workspace" \
        --entrypoint cp "$image" -r /opt/sim-deps/. /workspace/sim-deps/
fi
args=(--rm --init --gpus all --network host --hostname "$(hostname)" --user "$(id -u):$(id -g)"
      --ulimit stack=33554432 --ulimit memlock=-1
      --env PYTHONUNBUFFERED=1
      --env XDG_CACHE_HOME=/tmp/cache --env CUPY_CACHE_DIR=/tmp/cupy
      --env "TELESURGERY_PROJECT_ROOT=$root" --env "HOME=$HOME"
      --volume /etc/passwd:/etc/passwd:ro --volume /etc/group:/etc/group:ro
      --volume "$root:$root:ro" --volume "$workspace:$workspace" --workdir "$root"
      "${mounts[@]}")
if docker info --format '{{range $name, $_ := .Runtimes}}{{println $name}}{{end}}' | grep -qx nvidia; then
    args+=(--runtime=nvidia)
fi
# run.sh tees stdout to a log, so preserve its original terminal detection.
if [[ -t 0 && ( -t 1 || "${TELESURGERY_TTY:-}" == 1 ) ]]; then args+=(-it); fi
if [[ "${1:-}" == node ]]; then
    args+=(--cap-add SYS_NICE --ulimit rtprio=99)
    for device in /dev/video*; do
        if [[ -e "$device" ]]; then
            args+=(--device "$device" --group-add "$(stat -c %g "$device")")
        fi
    done
    if [[ -d /dev/v4l ]]; then args+=(--volume /dev/v4l:/dev/v4l:ro); fi
    if [[ -d /dev/bus/usb ]]; then
        args+=(--volume /dev/bus/usb:/dev/bus/usb --device-cgroup-rule 'c 189:* rwm')
    fi
    if [[ -d /run/udev ]]; then args+=(--volume /run/udev:/run/udev:ro); fi
fi
if [[ -n "${DISPLAY:-}" && -d /tmp/.X11-unix ]]; then
    args+=(--env DISPLAY --volume /tmp/.X11-unix:/tmp/.X11-unix:ro)
    display_auth="${XAUTHORITY:-$HOME/.Xauthority}"
    if [[ -f "$display_auth" ]]; then
        args+=(--env XAUTHORITY=/tmp/telesurgery-xauthority
               --volume "$display_auth:/tmp/telesurgery-xauthority:ro")
    fi
fi
# Simulation nodes use the host Docker service.
if [[ "${1:-}" == node ]]; then
    args+=(--volume /var/run/docker.sock:/var/run/docker.sock --group-add "$(stat -c %g /var/run/docker.sock)")
fi
docker run "${args[@]}" "$image" "${app_args[@]}"
