#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
sdk=5
docker=false
while (($#)); do
    case "$1" in
        --sdk) sdk="${2:?--sdk requires 4 or 5}"; shift 2 ;;
        --docker) docker=true; shift ;;
        -h|--help)
            echo "Usage: ./run.sh [--sdk 4] [--docker] {patient|surgeon|node|doctor} [options]"
            echo "Use ./run.sh patient --help for dashboard options."
            exit 0 ;;
        *) break ;;
    esac
done
[[ "$sdk" == 4 || "$sdk" == 5 ]] || { echo "SDK must be 4 or 5" >&2; exit 1; }
if $docker; then exec "$root/scripts/docker.sh" "$sdk" "$@"; fi
export TELESURGERY_SDK="$sdk"
python_bin="${TELESURGERY_PYTHON:-$root/.venv-sdk${sdk}/bin/python}"
if [[ ! -x "$python_bin" ]]; then
    sdk_option=""
    if [[ "$sdk" == 4 ]]; then sdk_option=" --sdk 4"; fi
    echo "Run ./setup.sh$sdk_option first." >&2
    exit 1
fi
ulimit -s 32768 2>/dev/null || true
exec "$python_bin" -m telesurgery "$@"
