# syntax=docker/dockerfile:1
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

FROM nvcr.io/nvidia/cuda:13.0.2-devel-ubuntu24.04
ARG SDK=5
ENV DEBIAN_FRONTEND=noninteractive \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video,graphics,display \
    UV_PROJECT_ENVIRONMENT=/opt/telesurgery \
    PATH=/opt/telesurgery/bin:$PATH \
    TELESURGERY_SDK=$SDK
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12-venv python3.12-dev build-essential ca-certificates curl git openssh-client \
    pkg-config libclang-dev libgl1 libglib2.0-0t64 libegl1 libxkbcommon0 docker.io chrony \
    libvulkan1 libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY dependencies ./dependencies
COPY packages ./packages
COPY scripts ./scripts
COPY native ./native
RUN --mount=type=cache,target=/root/.cache/uv \
    python3.12 scripts/dependencies.py --sdk "$SDK" --environment /opt/telesurgery
ARG CUDAARCHS=all-major
ENV CUDAARCHS=$CUDAARCHS
RUN mkdir -p /root/.ssh /opt/cuda-stubs \
    && ln -s /usr/local/cuda/lib64/stubs/libcuda.so /opt/cuda-stubs/libcuda.so.1
RUN --mount=type=ssh \
    --mount=type=secret,id=known_hosts,target=/root/.ssh/known_hosts \
    --mount=type=secret,id=ssh_config,target=/root/.ssh/config \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,id=telesurgery-build-${SDK},target=/app/build,sharing=locked \
    GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    LD_LIBRARY_PATH=/opt/cuda-stubs:$LD_LIBRARY_PATH sh -c 'if [ "$SDK" = 4 ]; then apt-get update && TELESURGERY_SDK4_DEVELOPMENT=/opt/sdk4-development python scripts/build_sdk4.py --prefix /opt/hololink; else python scripts/build_sdk5.py; fi' \
    && python scripts/build_pynvvideocodec.py --cuda-architectures "$CUDAARCHS" \
    && rm -rf /opt/cuda-stubs
# Isaac Sim uses its own Python, with only these small gateway dependencies mounted in.
RUN uv pip install --python /opt/telesurgery/bin/python --target /opt/sim-deps 'pyzmq>=26,<28' 'websockets>=14,<17'
ENTRYPOINT ["python", "-m", "telesurgery"]
CMD ["--help"]
