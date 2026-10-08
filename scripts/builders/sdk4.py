#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Install configured SDK and IMX274 dependencies into the current environment."""

from __future__ import annotations

import argparse
import os
import site
import sys
from pathlib import Path

from dependencies import ROOT, checkout, install, load, run


def development(sdk):
    sdk_prefix = Path(sdk.get("prefix", "/opt/nvidia/holoscan"))
    # Developer kits and the vendor container may install the SDK under another apt name.
    if not (sdk_prefix / "lib/cmake/holoscan").is_dir() and sdk.get("apt"):
        # Development files are relocatable; building a camera does not need a system install.
        development = Path(
            os.environ.get(
                "TELESURGERY_SDK4_DEVELOPMENT", ROOT / "build/third_party/sdk4-development"
            )
        )
        development.mkdir(parents=True, exist_ok=True)
        sdk_prefix = development / "opt/nvidia/holoscan"
        if not (sdk_prefix / "lib/cmake/holoscan").is_dir():
            for package in sdk["apt"]:
                run("apt-get", "download", package, cwd=development)
            for archive in development.glob("*.deb"):
                run("dpkg-deb", "--extract", archive, development)
    return sdk_prefix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependencies", type=Path, default=ROOT / "dependencies/sdk4.toml")
    parser.add_argument("--prefix", type=Path, default=ROOT / "build/hololink-install")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--component", choices=("all", "sdk", "camera"), default="all")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    specs = load(args.dependencies)
    sdk, hsb = specs["holoscan"], specs["hololink"]
    if sdk["provider"] == "git":
        parser.error("SDK 4 uses the released Python and development packages")
    if args.component != "camera":
        install({**sdk, "apt": []})
    if args.component == "sdk":
        return
    install(hsb)
    prefix = args.prefix.resolve()
    if hsb["provider"] == "git":
        sdk_prefix = development(sdk)
        source = checkout("hololink", hsb, ROOT / "build")
        build = ROOT / "build" / source.name
        run(
            "cmake",
            "-S",
            source,
            "-B",
            build,
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DCMAKE_INSTALL_PREFIX={prefix}",
            f"-DCMAKE_PREFIX_PATH={sdk_prefix}",
            f"-DPython3_EXECUTABLE={sys.executable}",
            f"-DCMAKE_CUDA_ARCHITECTURES={os.environ.get('CUDAARCHS', 'native')}",
            "-DHOLOLINK_BUILD_TESTS=OFF",
            "-DHOLOLINK_BUILD_TOOLS=OFF",
            "-DHOLOLINK_BUILD_EXAMPLES=OFF",
            "-DHOLOLINK_BUILD_ROCE=OFF",
            "-DHOLOLINK_BUILD_GPUNETIO_ROCE=OFF",
            "-DHOLOLINK_MODULE_BUILD_CRC=OFF",
            "-DHOLOLINK_BUILD_CRC=OFF",
        )
        run("cmake", "--build", build, "-j", args.jobs)
        run("cmake", "--install", build)
    else:
        prefix = Path(hsb.get("prefix", "/opt/nvidia/hololink"))
    paths = [prefix / "python", prefix / "python/lib"]
    Path(site.getsitepackages()[0], "telesurgery-hsb.pth").write_text(
        "".join(f"{p}\n" for p in paths if p.is_dir())
    )
    Path(sys.prefix, "hsb-modules").write_text(f"{prefix}/lib/hololink/modules\n")
    print(f"IMX274 support installed under {prefix}")


if __name__ == "__main__":
    main()
