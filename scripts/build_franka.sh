#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Optional Franka FCI adapter for robot protocol version 9.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
root=$PWD
sync_args=()
if [[ "${1:-}" == --no-install-workspace ]]; then
    sync_args+=(--no-install-workspace)
    shift
fi
if (($#)); then echo 'Usage: build_franka.sh [--no-install-workspace]' >&2; exit 1; fi
python=${UV_PROJECT_ENVIRONMENT:-$root/.venv-sdk${TELESURGERY_SDK:-5}}/bin/python
[[ -x "$python" ]] || { echo 'Run ./setup.sh first.' >&2; exit 1; }
PATH="$(dirname "$python"):$PATH"
export PATH
work=$root/build/franka
franka_prefix=${TELESURGERY_FRANKA_PREFIX:-$work/install}
source=$root/build/third_party/libfranka-d053f51c209c
mkdir -p "$work"
if ! dpkg-query -W -f='${Status}\n' libpoco-dev libeigen3-dev liburdfdom-headers-dev libfmt-dev 2>/dev/null | awk '
    /install ok installed/ { count++ } END { exit(count != 4) }'; then
    sudo apt-get update
    sudo apt-get install -y --no-remove --no-install-recommends libpoco-dev libeigen3-dev liburdfdom-headers-dev libfmt-dev
fi
UV_PROJECT_ENVIRONMENT="${python%/bin/python}" uv sync --locked --inexact --no-dev --package telesurgery-robots --extra franka "${sync_args[@]}"
if [[ ! -d "$source/.git" ]]; then
    git init -q "$source"
    git -C "$source" fetch --depth 1 https://github.com/frankarobotics/libfranka.git d053f51c209c2fc5626fc298b3a556e94c3bbc02
    git -C "$source" checkout --detach FETCH_HEAD
    git -C "$source" submodule update --init --depth 1
fi
prefix=$("$python" -c 'import sysconfig; print(sysconfig.get_path("purelib") + "/cmeel.prefix")')
cmake="$(dirname "$python")/cmake"
"$cmake" -S "$source" -B "$work/libfranka" -G Ninja \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="$prefix" -DCMAKE_INSTALL_PREFIX="$franka_prefix" \
    -DCMAKE_INSTALL_RPATH="$prefix/lib" -DBUILD_TESTS=OFF -DBUILD_EXAMPLES=OFF
"$cmake" --build "$work/libfranka" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-8}"
"$cmake" --install "$work/libfranka"
"$cmake" -S packages/robots/native -B "$work/bindings" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DPython_EXECUTABLE="$python" \
    -DCMAKE_PREFIX_PATH="$franka_prefix" \
    -DCMAKE_INSTALL_PREFIX="$root/packages/robots/src"
"$cmake" --build "$work/bindings" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-8}"
"$cmake" --install "$work/bindings"
PYTHONPATH="$root/packages/robots/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$python" -c 'from telesurgery_robots.franka._franka import Controller'
operator=${SUDO_USER:-$(id -un)}
if [[ "$operator" != root ]]; then
    limits="/etc/security/limits.d/90-telesurgery-franka-$operator.conf"
    if [[ ! -f "$limits" ]]; then
        printf '%s - rtprio 99\n' "$operator" | sudo install -m 644 /dev/stdin "$limits"
        echo 'Realtime scheduling configured. Start the node in a new login session.'
    fi
fi
echo 'Franka adapter installed. Restart the node service.'
