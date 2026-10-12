# syntax=docker/dockerfile:1
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

FROM nvcr.io/nvidia/cuda:13.0.2-devel-ubuntu24.04 AS dependencies
ENV DEBIAN_FRONTEND=noninteractive \
    UV_PROJECT_ENVIRONMENT=/opt/telesurgery \
    UV_LINK_MODE=copy \
    PATH=/opt/telesurgery/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12-venv python3.12-dev build-essential ca-certificates curl git openssh-client \
    pkg-config libclang-dev libgl1 libglib2.0-0t64 libegl1 libxkbcommon0 \
    libvulkan1 libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxi-dev \
    libpoco-dev libeigen3-dev liburdfdom-headers-dev libfmt-dev libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
WORKDIR /app
# Resolve third-party dependencies from metadata, independently of Python/UI source.
COPY pyproject.toml uv.lock ./
COPY packages/app/pyproject.toml ./packages/app/
COPY packages/core/pyproject.toml ./packages/core/
COPY packages/robots/pyproject.toml ./packages/robots/
COPY packages/runtime/pyproject.toml ./packages/runtime/
COPY packages/sim/pyproject.toml ./packages/sim/
COPY scripts/builders/dependencies.py ./scripts/builders/
ARG SDK=5
ENV TELESURGERY_SDK=$SDK
RUN --mount=type=cache,target=/root/.cache/uv \
    python3.12 scripts/builders/dependencies.py --sdk "$SDK" --environment /opt/telesurgery --dependencies-only

FROM dependencies AS native-build
ARG CUDAARCHS=all-major
ENV CUDAARCHS=$CUDAARCHS
COPY dependencies ./dependencies
COPY scripts/builders/sdk4.py scripts/builders/sdk5.py ./scripts/builders/
RUN mkdir -p /root/.ssh /opt/holoscan /opt/hololink /opt/sdk4-development
RUN --mount=type=ssh \
    --mount=type=secret,id=known_hosts,target=/root/.ssh/known_hosts \
    --mount=type=secret,id=ssh_config,target=/root/.ssh/config \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,id=telesurgery-build-${SDK},target=/app/build,sharing=locked \
    mkdir -p /opt/cuda-stubs \
    && ln -s /usr/local/cuda/lib64/stubs/libcuda.so /opt/cuda-stubs/libcuda.so.1 \
    && GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    LD_LIBRARY_PATH=/opt/cuda-stubs:$LD_LIBRARY_PATH sh -c \
    'if [ "$TELESURGERY_SDK" = 4 ]; then python scripts/builders/sdk4.py --component sdk; else python scripts/builders/sdk5.py --component sdk --prefix /opt/holoscan; fi' \
    && rm -rf /opt/cuda-stubs
# Native sources invalidate their own builds, while application edits reuse them.
COPY native ./native
RUN --mount=type=ssh \
    --mount=type=secret,id=known_hosts,target=/root/.ssh/known_hosts \
    --mount=type=secret,id=ssh_config,target=/root/.ssh/config \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,id=telesurgery-build-${SDK},target=/app/build,sharing=locked \
    mkdir -p /opt/cuda-stubs \
    && ln -s /usr/local/cuda/lib64/stubs/libcuda.so /opt/cuda-stubs/libcuda.so.1 \
    && GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    LD_LIBRARY_PATH=/opt/cuda-stubs:$LD_LIBRARY_PATH sh -c \
    'if [ "$TELESURGERY_SDK" = 4 ]; then apt-get update && TELESURGERY_SDK4_DEVELOPMENT=/opt/sdk4-development python scripts/builders/sdk4.py --component camera --prefix /opt/hololink; else python scripts/builders/sdk5.py --component camera --prefix /opt/holoscan; fi' \
    && rm -rf /opt/cuda-stubs /var/lib/apt/lists/*
COPY scripts/build_franka.sh ./scripts/
COPY packages/robots/native ./packages/robots/native
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,id=telesurgery-build-${SDK},target=/app/build,sharing=locked \
    TELESURGERY_FRANKA_PREFIX=/opt/franka scripts/build_franka.sh --no-install-workspace
# Install the patched codec after dependency syncs, which could replace its wheel.
COPY scripts/builders/codecs.py ./scripts/builders/
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,id=telesurgery-build-${SDK},target=/app/build,sharing=locked \
    python scripts/builders/codecs.py \
    && uv pip uninstall --python /opt/telesurgery/bin/python cmake ninja patchelf nanobind
# Isaac Sim runs in its own container with these small gateway dependencies.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/telesurgery/bin/python --target /opt/sim-deps \
    'pyzmq>=26,<28' 'websockets>=14,<17' 'ruckig==0.19.4' 'trimesh==5.1.0'

FROM native-build AS application
COPY packages ./packages
# Keep editable package metadata separate from the large, cached dependency environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/telesurgery/bin/python --prefix /opt/application --no-deps \
    --editable packages/core --editable packages/robots --editable packages/runtime \
    --editable packages/sim --editable packages/app

FROM nvcr.io/nvidia/cuda:13.0.2-runtime-ubuntu24.04 AS runtime
ENV DEBIAN_FRONTEND=noninteractive \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video,graphics,display \
    PATH=/opt/telesurgery/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12-venv ca-certificates chrony docker.io libgl1 libglib2.0-0t64 libegl1 libxkbcommon0 \
    libvulkan1 libx11-6 libxrandr2 libxinerama1 libxcursor1 libxi6 \
    libpoconet80t64 libpocofoundation80t64 libfmt9 libgomp1 libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ARG SDK=5
ENV TELESURGERY_SDK=$SDK
# CuPy compiles kernels with NVRTC at runtime and needs CUDA headers, but no compiler.
COPY --from=native-build /usr/local/cuda/include/ /usr/local/cuda/include/
COPY --from=native-build /opt/telesurgery /opt/telesurgery
COPY --from=native-build /opt/hololink /opt/hololink
COPY --from=native-build /opt/sdk4-development /opt/sdk4-development
COPY --from=native-build /opt/franka /opt/franka
COPY --from=native-build /opt/sim-deps /opt/sim-deps
# Application-only rebuilds replace just these small layers.
COPY --from=application /opt/application/ /opt/telesurgery/
COPY --from=application /app/packages ./packages
COPY pyproject.toml uv.lock README.md LICENSE NOTICE SECURITY.md ./
ENTRYPOINT ["python", "-m", "telesurgery"]
CMD ["--help"]
