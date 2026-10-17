#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

fail() { echo "$*" >&2; exit 1; }

sdk=5
automatic=true
docker=false
franka=false
force=false
workspace="$root/workspace"
while (($#)); do
    case "$1" in
        --sdk)
            [[ $# -ge 2 && ( "$2" == 4 || "$2" == 5 ) ]] || fail "--sdk requires 4 or 5"
            sdk="$2"; automatic=false; shift 2 ;;
        --docker) docker=true; shift ;;
        --force) force=true; shift ;;
        --profile)
            [[ $# -ge 2 && "$2" == franka ]] || fail "--profile requires franka"
            franka=true; shift 2 ;;
        --workspace)
            [[ $# -ge 2 && -n "$2" ]] || fail "--workspace requires a directory"
            workspace="$(realpath -m -- "$2")"; shift 2 ;;
        --workspace=*) workspace="$(realpath -m -- "${1#*=}")"; shift ;;
        -h|--help)
            echo "Usage: ./setup.sh [--docker] [--workspace PATH] [--profile franka] [--force]"
            echo "Install native dependencies, or prepare only the host clock for Docker."
            echo "Add --profile franka to build the physical Franka adapter for native execution."
            echo "Unchanged native setups are reused; --force reruns installation and validation."
            exit 0 ;;
        *) fail "Unknown option: $1. Use --help for usage." ;;
    esac
done

export TELESURGERY_SDK="$sdk"
export PATH="$root/build/tools/bin:$HOME/.local/bin:/usr/local/cuda/bin:$PATH"
if [[ "$(uname -s)" != Linux ]] || ! command -v apt-get >/dev/null; then
    fail "Setup requires Ubuntu or Debian Linux."
fi
if ! $docker; then
    if ! command -v nvcc >/dev/null || [[ "$(nvcc --version)" != *"release 13."* ]]; then
        fail "Install the CUDA 13 development toolkit first; see README.md."
    fi
fi

python3 scripts/clock_sync.py
python3 scripts/setup_gamepads.py

glib=libglib2.0-0
if dpkg-query -W libglib2.0-0t64 >/dev/null 2>&1; then glib=libglib2.0-0t64; fi
packages=(build-essential ca-certificates curl git pkg-config libgl1 libegl1
          libxkbcommon0 libvulkan1 "$glib" libx11-dev libxrandr-dev
          libxinerama-dev libxcursor-dev libxi-dev libusb-1.0-0 libusb-0.1-4
          libsdl2-2.0-0 python3-tk python3-websocket xvfb xauth python3-yaml)
# Haply Hub's host device manager also needs the legacy USB library with Docker.
if $docker; then packages=(python3-yaml libusb-0.1-4); fi
missing=()
for package in "${packages[@]}"; do
    if [[ "$(dpkg-query -W -f='${db:Status-Status}' "${package%%=*}" 2>/dev/null || true)" != installed ]]; then
        missing+=("$package")
    fi
done
if ((${#missing[@]})); then
    elevate=()
    if ((EUID != 0)); then elevate=(sudo); fi
    echo "Installing system dependencies…"
    "${elevate[@]}" apt-get update
    "${elevate[@]}" apt-get install -y --no-remove --no-install-recommends "${missing[@]}"
fi
if $docker; then exit 0; fi

# Keep the default runtime for dashboards/simulations and add isolated camera
# support when this host has an HSB board or saved HSB node configuration.
if $automatic; then
    # python3-yaml is installed by apt for the system interpreter, not Conda or a venv.
    detected="$(/usr/bin/python3 scripts/select_runtime.py --workspace "$workspace" --all-nodes)"
    if [[ "$detected" == 4 ]]; then
        camera_args=(--sdk 4 --workspace "$workspace")
        if $franka; then camera_args+=(--profile franka); fi
        if $force; then camera_args+=(--force); fi
        echo "Preparing HSB camera support…"
        bash "$root/setup.sh" "${camera_args[@]}"
    fi
fi

if [[ "$sdk" == 5 ]] && ! printf '#include <format>\n' |
    "${CXX:-c++}" -std=c++20 -x c++ -fsyntax-only - >/dev/null 2>&1; then
    fail "SDK 5 native builds need C++20 <format> support (GCC 13+). Use --docker or a newer compiler."
fi

mkdir -p build
if ! command -v uv >/dev/null; then
    curl -fLsS https://astral.sh/uv/0.12.21/install.sh -o build/install-uv.sh
    UV_INSTALL_DIR="$root/build/tools/bin" UV_NO_MODIFY_PATH=1 sh build/install-uv.sh
fi

environment="$root/.venv-sdk$sdk"
python_bin="$environment/bin/python"
setup_path="$PATH"
mkdir -p build/setup
pending="$(mktemp "$root/build/setup/run.XXXXXX")"
trap 'rm -f -- "$pending"' EXIT
cache_args=(--sdk "$sdk" --workspace "$workspace" --pending "$pending")
if $franka; then cache_args+=(--franka); fi
if $force; then cache_args+=(--force); fi
cache_python=python3
if [[ -x "$python_bin" ]]; then cache_python="$python_bin"; fi
if "$cache_python" scripts/setup_cache.py check "${cache_args[@]}"; then
    echo "Setup already up to date. Use --force to rerun installation and validation."
    exit 0
fi
export UV_MANAGED_PYTHON=1
log="$root/build/setup.log"
: > "$log"
echo "Setup details: $log"
# Keep Python progress messages visible when output is piped to the log.
export PYTHONUNBUFFERED=1
step() {
    local label="$1" started=$SECONDS
    echo "$label" | tee -a "$log"
    shift
    if ! "$@" 2>&1 | tee -a "$log"; then
        tail -n 30 "$log" >&2
        fail "Setup failed. See $log"
    fi
    echo "${label%…} finished in $((SECONDS - started))s." | tee -a "$log"
}

step "Preparing Python environment…" uv run --no-project --python 3.12 \
    python scripts/builders/dependencies.py \
    --sdk "$sdk" --environment "$environment"
export PATH="$environment/bin:$PATH"
step "Preparing Haply input support…" "$python_bin" scripts/setup_haply.py
step "Building SDK and camera support…" "$python_bin" "scripts/builders/sdk$sdk.py"
step "Preparing GPU codecs…" "$python_bin" scripts/builders/codecs.py
if $franka; then
    step "Building Franka support…" env UV_PROJECT_ENVIRONMENT="$environment" scripts/build_franka.sh
fi
step "Preparing simulation dependencies…" uv pip install --python "$python_bin" \
    --target "$workspace/sim-deps" 'pyzmq>=26,<28' 'websockets>=14,<17' 'ruckig==0.19.4'
step "Preparing simulation meshes…" uv pip install --python "$python_bin" \
    --target "$workspace/sim-deps" --no-deps 'trimesh==5.1.1'
step "Checking GPU codecs…" "$python_bin" -m telesurgery doctor
PATH="$setup_path" "$python_bin" scripts/setup_cache.py record "${cache_args[@]}"

echo "Setup complete."
