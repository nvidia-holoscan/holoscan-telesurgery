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
            echo "Usage: ./run.sh [--sdk 4] [--docker] {patient|surgeon|node|controller|doctor} [options]"
            echo "Use ./run.sh patient --help for dashboard options."
            exit 0 ;;
        *) break ;;
    esac
done
[[ "$sdk" == 4 || "$sdk" == 5 ]] || { echo "SDK must be 4 or 5" >&2; exit 1; }

role="${1:-}"
if [[ "$role" == patient || "$role" == surgeon || "$role" == node ]]; then
    workspace="$root/workspace"
    name="" sim="" port="" help=false
    app_args=("$@")
    for ((i=1; i<${#app_args[@]}; i++)); do
        option="${app_args[i]%%=*}"
        case "$option" in
            --workspace|--name|--sim|--port)
                if [[ "${app_args[i]}" == *=* ]]; then
                    value="${app_args[i]#*=}"
                else
                    ((i+=1))
                    value="${app_args[i]:?option requires a value}"
                fi
                case "$option" in
                    --workspace) workspace="$value" ;;
                    --name) name="$value" ;;
                    --sim) sim="$value" ;;
                    --port) port="$value" ;;
                esac ;;
            -h|--help) help=true ;;
        esac
    done
    if ! $help; then
        case "$role" in
            node) name="${name:-$(hostname)${sim:+-$sim}}" ;;
            patient) name="${port:-8000}" ;;
            surgeon) name="${port:-8002}" ;;
        esac
        name="${name//[^a-zA-Z0-9_.-]/_}"
        logs="$(realpath -m -- "$workspace")/logs"
        (umask 077; mkdir -p -- "$logs")
        log="$(mktemp "$logs/$role-$name-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.log")"
        if [[ -t 0 && -t 1 ]]; then export TELESURGERY_TTY=1; fi
        export PYTHONUNBUFFERED=1
        # Keep the application PID and exit status; retain shutdown output on Ctrl+C.
        exec > >(tee -ai -- "$log") 2>&1
        printf 'Log: %s\n' "$log"
    fi
fi
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
