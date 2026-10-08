#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build NVIDIA's pinned source with an explicit NVENC output-delay argument.

Run with the application's Python; the built wheel is installed into that interpreter.
Requires uv, a C++ compiler, and the CUDA Toolkit. Downloads and build products
stay under build/codec. NVIDIA's source and license notices are preserved there.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

from dependencies import ROOT, run

VERSION = "2.2.3+telesurgery.1"
ARCHIVE = "PyNvVideoCodec_2.2.3.zip"
URL = (
    f"https://api.ngc.nvidia.com/v2/resources/nvidia/pynvvideocodec/versions/v2.2.3/files/{ARCHIVE}"
)
SHA256 = "29f7c0694d683266c563aca9a4f8e979ba0c5dce8f0ccc1efe500073e0948be0"


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"source patch does not match {path}: {old!r}")
    path.write_text(text.replace(old, new))


def patch(source):
    encoder = source / "src/PyNvVideoCodec/src/PyNvEncoder.cpp"
    replace_once(
        encoder,
        "        NV_ENC_BUFFER_FORMAT eBufferFormat;",
        """        // Default is unchanged for other users of this locally built library.
        int extraOutputDelay = 3;
        if (options.count("extra_output_delay")) {
            extraOutputDelay = std::stoi(options.at("extra_output_delay"));
            if (extraOutputDelay < 0 || extraOutputDelay > 16) {
                throw std::invalid_argument("extra_output_delay must be in [0, 16]");
            }
            options.erase("extra_output_delay");
        }
        NV_ENC_BUFFER_FORMAT eBufferFormat;""",
    )
    replace_once(
        encoder,
        "                3, false, false, useIvfContainer, true);",
        "                extraOutputDelay, false, false, useIvfContainer, true);",
    )
    replace_once(
        encoder,
        "(cudacontext, cudastream, _width, _height, eBufferFormat);",
        "(cudacontext, cudastream, _width, _height, eBufferFormat, extraOutputDelay);",
    )
    replace_once(
        source / "src/PyNvVideoCodec/src/PyNvVideoCodec.cpp",
        "PYBIND11_MODULE(_PyNvVideoCodec, m)\n{",
        'PYBIND11_MODULE(_PyNvVideoCodec, m)\n{\n    m.attr("telesurgery_low_latency_patch") = 1;',
    )
    # Upstream's pybind11 2.10 predates Python 3.12 support.
    cmake = source / "src/PyNvVideoCodec/CMakeLists.txt"
    replace_once(
        cmake,
        "https://github.com/pybind/pybind11/archive/v2.10.0.tar.gz",
        "https://codeload.github.com/pybind/pybind11/tar.gz/refs/tags/v2.13.6",
    )
    replace_once(
        cmake,
        "eacf582fa8f696227988d08cfc46121770823839fe9e301a20fbce67e7cd70ec",
        "e08cb87f4773da97fa7b5f035de8763abc656d87d5773e62f6da0587d1f0ec20",
    )
    for filename in ("setup.py", "pyproject.toml", "src/PyNvVideoCodec/__init__.py"):
        replace_once(source / filename, '"2.2.3"', f'"{VERSION}"')


def build_wheel(args):
    build = ROOT / "build/codec"
    build.mkdir(parents=True, exist_ok=True)
    stamp = build / "build-options.txt"
    options = f"{VERSION}:{sys.version_info[:2]}:{os.uname().machine}:{args.cuda_architectures}"
    candidates = list(
        (build / "wheels").glob(
            f"pynvvideocodec-{VERSION}-cp{sys.version_info.major}{sys.version_info.minor}-*.whl"
        )
    )
    if candidates and stamp.exists() and stamp.read_text() == options:
        wheel = max(candidates, key=lambda path: path.stat().st_mtime_ns)
        return wheel
    archive = build / ARCHIVE
    if not archive.exists():
        print(f"Downloading {URL}", flush=True)
        temporary = archive.with_suffix(".download")
        # Fixed HTTPS URL, SHA256 verified below.
        urllib.request.urlretrieve(URL, temporary)  # nosec B310
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError(f"SHA256 mismatch: remove {archive} and retry")
    # Re-extract a verified source so patches never stack across runs.
    source = build / "source"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(source)
    source = source / "PyNvVideoCodec_2.2.3"
    patch(source)
    wheels = build / "wheels"
    env = os.environ.copy()
    env["CMAKE_ARGS"] = (
        env.get("CMAKE_ARGS", "") + f" -DCMAKE_CUDA_ARCHITECTURES={args.cuda_architectures}"
    )
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(args.jobs)
    run("uv", "build", "--python", sys.executable, source, "--wheel", "--out-dir", wheels, env=env)
    candidates = list(
        wheels.glob(
            f"pynvvideocodec-{VERSION}-cp{sys.version_info.major}{sys.version_info.minor}-*.whl"
        )
    )
    if not candidates:
        raise RuntimeError(f"Codec build did not produce a wheel for {sys.executable}")
    wheel = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    stamp.write_text(options)
    print(f"Built {wheel}\nSHA256: {hashlib.sha256(wheel.read_bytes()).hexdigest()}", flush=True)
    return wheel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cuda-architectures", default=os.environ.get("CUDAARCHS", "native"))
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    run("uv", "pip", "install", "--python", sys.executable, build_wheel(args))


if __name__ == "__main__":
    main()
