#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

fail() { echo "$*" >&2; exit 1; }

sdk=5
docker=false
workspace="$root/workspace"
while (($#)); do
    case "$1" in
        --sdk)
            [[ $# -ge 2 && ( "$2" == 4 || "$2" == 5 ) ]] || fail "--sdk requires 4 or 5"
            sdk="$2"; shift 2 ;;
        --docker) docker=true; shift ;;
        --workspace)
            [[ $# -ge 2 && -n "$2" ]] || fail "--workspace requires a directory"
            workspace="$(realpath -m -- "$2")"; shift 2 ;;
        --workspace=*) workspace="$(realpath -m -- "${1#*=}")"; shift ;;
        -h|--help)
            echo "Usage: ./setup.sh [--sdk 4] [--docker] [--workspace PATH]"
            echo "Install native dependencies, or prepare only the host clock for Docker."
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
if $docker; then exit 0; fi

glib=libglib2.0-0
if dpkg-query -W libglib2.0-0t64 >/dev/null 2>&1; then glib=libglib2.0-0t64; fi
packages=(build-essential ca-certificates curl git pkg-config libgl1 libegl1
          libxkbcommon0 libvulkan1 "$glib" libx11-dev libxrandr-dev
          libxinerama-dev libxcursor-dev libxi-dev libusb-1.0-0)
missing=()
for package in "${packages[@]}"; do
    if [[ "$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)" != installed ]]; then
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
export UV_MANAGED_PYTHON=1
log="$root/build/setup.log"
: > "$log"
echo "Setup details: $log"
step() {
    echo "$1"
    shift
    if ! "$@" >> "$log" 2>&1; then
        tail -n 30 "$log" >&2
        fail "Setup failed. See $log"
    fi
}

step "Preparing Python environment…" uv run --no-project --python 3.12 \
    python scripts/builders/dependencies.py \
    --sdk "$sdk" --environment "$environment"
export PATH="$environment/bin:$PATH"
step "Building SDK and camera support…" "$python_bin" "scripts/builders/sdk$sdk.py"
step "Preparing GPU codecs…" "$python_bin" scripts/builders/codecs.py
step "Preparing simulation dependencies…" uv pip install --python "$python_bin" \
    --target "$workspace/sim-deps" 'pyzmq>=26,<28' 'websockets>=14,<17' 'ruckig==0.19.4'
step "Checking GPU codecs…" "$python_bin" -m telesurgery doctor

echo "Setup complete."
