#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
sdk="$1"
shift
workspace="$(realpath -m -- "$root/workspace")"
app_args=("$@")
mounts=()
simulation=false
mira=false
api_supplied=false
api_path=""
help=false
role="${1:-}"
name="" port="" sim=""
for ((i=0; i<${#app_args[@]}; i++)); do
    option="${app_args[i]%%=*}"
    case "$option" in
        --workspace|--ssl-cert|--ssl-key|--mira-api)
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
                if [[ "$option" == --mira-api ]]; then
                    api_supplied=true
                    api_path="$path"
                else
                    mounts+=(--volume "$path:$path:ro")
                fi
            fi
            if [[ "$index" == "$i" ]]; then
                app_args[i]="$option=$path"
            else
                app_args[i]="$path"
            fi ;;
        --name|--port|--sim)
            if [[ "${app_args[i]}" == *=* ]]; then
                value="${app_args[i]#*=}"
            else
                ((i+=1))
                value="${app_args[i]:?option requires a value}"
            fi
            case "$option" in
                --name) name="$value" ;;
                --port) port="$value" ;;
                --sim) sim="$value"; simulation=true ;;
            esac ;;
        --profile)
            if [[ "${app_args[i]}" == *=* ]]; then
                profile="${app_args[i]#*=}"
            else
                ((i+=1))
                profile="${app_args[i]:?--profile requires a value}"
            fi
            if [[ "$profile" == mira ]]; then mira=true; fi ;;
        -h|--help) help=true ;;
    esac
done
# Ask on the host so a file outside the workspace can be mounted into the node.
if [[ "${1:-}" == node && -t 0 ]] && $mira && ! $api_supplied && ! $simulation && ! $help &&
    [[ ! -f "$workspace/mira-api" ]]; then
    read -r -p 'Path to the vendor MIRA API executable: ' path
    [[ -n "$path" ]] || { echo "MIRA API path is required; use --mira-api PATH" >&2; exit 1; }
    if [[ "$path" == \~/* ]]; then path="$HOME/${path:2}"; fi
    api_path="$(realpath -e -- "$path")"
    [[ -f "$api_path" ]] || { echo "MIRA API must be a file: $api_path" >&2; exit 1; }
    app_args+=(--mira-api "$api_path")
fi
# The default file is already in the writable workspace and may need executable permissions.
if [[ -n "$api_path" && "$api_path" != "$workspace/mira-api" ]]; then
    mounts+=(--volume "$api_path:$api_path:ro")
fi
version="$(sed -n 's/^version = "\([^"]*\)"$/\1/p' "$root/pyproject.toml")"
[[ -n "$version" ]] || { echo "Missing project version in pyproject.toml" >&2; exit 1; }
image="holoscan-telesurgery:$version"
if [[ "$sdk" == 4 ]]; then image+="-sdk4"; fi
if ! command -v docker >/dev/null; then
    echo "Install Docker and NVIDIA Container Toolkit first." >&2
    exit 1
fi
if [[ "${1:-}" == patient || "${1:-}" == surgeon || "${1:-}" == node ]] &&
    ! command -v chronyc >/dev/null &&
    ! systemctl is-enabled --quiet ptp4l phc2sys ntp ntpsec 2>/dev/null; then
    "$root/setup.sh" --docker --sdk "$sdk"
fi
# Use the host's routes for dependency downloads on VPN and restricted networks.
build_args=(--network host --build-arg "SDK=$sdk")
if [[ -n "${CUDAARCHS:-}" ]]; then build_args+=(--build-arg "CUDAARCHS=$CUDAARCHS"); fi
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
if ! $help && [[ "$role" == patient || "$role" == surgeon || "$role" == node ]]; then
    case "$role" in
        patient) instance="${port:-8000}" ;;
        surgeon) instance="${port:-8002}" ;;
        node) instance="${name:-$(hostname)${sim:+-$sim}}" ;;
    esac
    identity="$(printf '%s\0' "$workspace" "$role" "$instance" "$(id -u)" | sha256sum)"
    safe_instance="${instance//[^a-zA-Z0-9_.-]/_}"
    label=com.nvidia.telesurgery
    args+=(--name "telesurgery-$role-${safe_instance:0:64}-${identity:0:12}"
           --label "$label.workspace=$workspace" --label "$label.role=$role"
           --label "$label.instance=$instance" --label "$label.uid=$(id -u)"
           --label "$label.log=${TELESURGERY_LOG:-}"
           --env TELESURGERY_CONTAINER=1 --stop-timeout 30)
fi
if docker info --format '{{range $name, $_ := .Runtimes}}{{println $name}}{{end}}' | grep -qx nvidia; then
    args+=(--runtime=nvidia)
fi
# Docker's legacy --gpus hook can inject the driver libraries without either
# discovery manifest (observed on Spark). Vulkan also needs GLVND to find the
# matching NVIDIA EGL driver; mounting only the Vulkan manifest is insufficient.
for manifest in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
    if [[ -f "$manifest" ]]; then
        args+=(--volume "$manifest:/etc/vulkan/icd.d/nvidia_icd.json:ro")
        break
    fi
done
if [[ -f /usr/share/glvnd/egl_vendor.d/10_nvidia.json ]]; then
    args+=(--volume /usr/share/glvnd/egl_vendor.d/10_nvidia.json:/usr/share/glvnd/egl_vendor.d/10_nvidia.json:ro)
fi
# run.sh tees stdout to a log, so preserve its original terminal detection.
if [[ -t 0 && ( -t 1 || "${TELESURGERY_TTY:-}" == 1 ) ]]; then args+=(-it); fi
if [[ "${1:-}" == node ]] && ! $simulation; then
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
if [[ "${1:-}" == surgeon && -d /dev/input ]]; then
    for device in /dev/input/event*; do
        if [[ -c "$device" ]] && udevadm info --query=property --name="$device" |
            grep -qx 'ID_INPUT_JOYSTICK=1'; then
            args+=(--device "$device" --group-add "$(stat -c %g "$device")")
        fi
    done
    if [[ -d /run/udev ]]; then args+=(--volume /run/udev:/run/udev:ro); fi
fi
if [[ "${1:-}" == surgeon || "${1:-}" == controller ]]; then
    # Grant only Haply serial endpoints, leaving unrelated ACM devices alone.
    for device in /dev/serial/by-id/usb-Teensyduino_Haply_inverse3_* \
                  /dev/serial/by-id/usb-ZEPHYR_Haply_USB_Transceiver_*; do
        if [[ -c "$device" ]]; then
            endpoint="$(readlink -f -- "$device")"
            args+=(--device "$endpoint" --group-add "$(stat -c %g "$endpoint")")
        fi
    done
fi
# Simulation and managed physical MIRA controllers use the host Docker service.
if [[ "${1:-}" == node ]]; then
    args+=(--volume /var/run/docker.sock:/var/run/docker.sock --group-add "$(stat -c %g /var/run/docker.sock)")
fi
docker run "${args[@]}" "$image" "${app_args[@]}"
