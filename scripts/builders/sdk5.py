#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Download and build pinned SDK 5 and IMX274 bindings under build/.

Prerequisites: Python 3.12, uv, CMake 4, Ninja, Rust/cargo, a C++20 compiler,
CUDA 13 toolkit, patchelf, and NVIDIA GitLab SSH access for Hololink.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import sys
import tarfile
from pathlib import Path

from dependencies import ROOT, checkout, install, load, run


def rust(work):
    cargo = work / "toolchain/cargo"
    os.environ.update(CARGO_HOME=str(cargo), RUSTUP_HOME=str(work / "toolchain/rustup"))
    os.environ["PATH"] = f"{cargo}/bin:{os.environ['PATH']}"
    if not (cargo / "bin/cargo").exists():
        installer = work / "install-rust.sh"
        run("curl", "-fLsS", "https://sh.rustup.rs", "-o", installer)
        run(
            "sh",
            installer,
            "-y",
            "--no-modify-path",
            "--profile",
            "minimal",
            "--default-toolchain",
            "1.91.1",
        )


def slang(source, work):
    """Fetch the shader compiler pinned by this SDK source, without a system install."""
    recipe = (source / "cmake/deps/slang.cmake").read_text()
    version = re.search(r"set\(HOLOSCAN_SLANG_VERSION ([^)]+)\)", recipe)[1]
    arch = platform.machine()
    package_arch = {"x86_64": "AMD64", "aarch64": "ARM64"}[arch]
    checksum = re.search(
        rf"ARG SLANG_SHA256_{package_arch}=([a-f0-9]{{64}})", (source / "Dockerfile").read_text()
    )[1]
    target = work / "toolchain" / f"slang-{version}-{arch}-{checksum[:12]}"
    if not (target / "bin/slangc").exists():
        target.mkdir(parents=True, exist_ok=True)
        archive = target / "slang.tar.gz"
        run(
            "curl",
            "-fLsS",
            "--retry",
            "3",
            f"https://github.com/shader-slang/slang/releases/download/v{version}/"
            f"slang-{version}-linux-{arch}.tar.gz",
            "-o",
            archive,
        )
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
            raise RuntimeError("Slang shader compiler checksum did not match the SDK pin")
        with tarfile.open(archive) as package:
            package.extractall(target, filter="data")
        archive.unlink()
    os.environ["PATH"] = f"{target}/bin:{os.environ['PATH']}"


def wheel_project(source, build, version, module="core"):
    """Package the SDK's CMake wheel component, including from a public source-only tree."""
    project = build / f"wheel-{module}-project"
    project.mkdir(exist_ok=True)
    requirements = [
        line.strip()
        for line in (source / "python/requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if module != "core":
        requirements = [f"holoscan-core-cu13=={version}"]
    (project / "pyproject.toml").write_text(f'''[build-system]
requires = ["scikit-build-core==1.0.3", "patchelf"]
build-backend = "scikit_build_core.build"
[project]
name = "holoscan-{module}-cu13"
version = "{version}"
requires-python = ">=3.12"
dependencies = {json.dumps(requirements)}
license-files = ["LICENSE.txt", "NOTICE.txt"]
[tool.scikit-build]
wheel.packages = []
wheel.py-api = "cp312"
install.components = ["holoscan-wheel-{module}"]
''')
    (project / "CMakeLists.txt").write_text(
        """cmake_minimum_required(VERSION 3.24)
project(holoscan_wheel LANGUAGES NONE)
if(NOT EXISTS "${HOLOSCAN_SDK_BUILD_ROOT}/cmake_install.cmake")
  message(FATAL_ERROR "Build the SDK before packaging it")
endif()
string(CONFIGURE [[
  execute_process(COMMAND "${CMAKE_COMMAND}" --install "@HOLOSCAN_SDK_BUILD_ROOT@"
    --component holoscan-wheel-core --prefix "${CMAKE_INSTALL_PREFIX}"
    COMMAND_ERROR_IS_FATAL ANY)
]] code @ONLY)
install(CODE "${code}" COMPONENT holoscan-wheel-core)
""".replace("holoscan-wheel-core", f"holoscan-wheel-{module}")
    )
    for origin, name in [
        (source / "LICENSE.txt", "LICENSE.txt"),
        (source / "cmake/modules/cpack/NOTICE.txt", "NOTICE.txt"),
    ]:
        shutil.copy2(origin, project / name)
    return project


def build_holoscan(sdk_spec, work, args):
    source = checkout("holoscan", sdk_spec, work)
    build = work / source.name
    prefix = build / "install"
    rust(work)
    slang(source, work)
    version = sdk_spec["version"]
    disabled = (
        "EXAMPLES",
        "TESTS",
        "TESTING_LIBRARY",
        "BENCHMARKS",
        "VISION",
        "INFERENCE",
    )
    flags = [f"-DHOLOSCAN_BUILD_{key}=OFF" for key in disabled]
    run(
        "cmake",
        "-S",
        source,
        "-B",
        build,
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_CUDA_ARCHITECTURES={args.cuda_architectures}",
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
        f"-DPython3_EXECUTABLE={sys.executable}",
        "-DHOLOSCAN_DOWNLOAD_DATASETS=OFF",
        "-DHOLOSCAN_INSTALL_EXAMPLE_SOURCE=OFF",
        "-DHOLOSCAN_USE_SCCACHE=OFF",
        "-DHOLOSCAN_BUILD_PYTHON_STUBS=OFF",
        "-DHOLOSCAN_BUILD_VISUALIZATION=ON",
        "-DGLFW_BUILD_WAYLAND=OFF",
        "-DVOLK_HEADERS_ONLY=ON",
        "-DCPM_DOWNLOAD_ALL=ON",
        *flags,
    )
    run("cmake", "--build", build, "-j", args.jobs)
    run("cmake", "--install", build)
    wheels = build / "wheels"
    for module in ("core", "visualization"):
        run(
            "uv",
            "build",
            "--python",
            sys.executable,
            wheel_project(source, build, version, module),
            "--wheel",
            "--out-dir",
            wheels,
            f"-Ccmake.define.HOLOSCAN_SDK_BUILD_ROOT={build}",
            env={**os.environ, "CUDA_MAJOR": "13", "PEP440_VERSION": version},
        )
        wheel = next(wheels.glob(f"holoscan_{module}_cu13-{version}-*.whl"))
        run("uv", "pip", "install", "--python", sys.executable, wheel)
    return prefix


def build_camera(specs, work, prefixes, args):
    hsb = (
        checkout("hololink", specs["hololink"], work)
        if specs["hololink"]["provider"] == "git"
        else None
    )
    # Importing also verifies that a package/apt provider supplies the required Python API.
    from telesurgery_runtime.backends.sdk import require_sdk

    hs = require_sdk()
    # Package providers must supply the visualization companion alongside Core.
    from holoscan_visualization.operators import HolovizOp  # noqa: F401

    prefixes.insert(0, str(Path(hs.__file__).parent))
    hololink = importlib.util.find_spec("hololink")
    if hololink and hololink.origin:
        prefixes.append(str(Path(hololink.origin).parent))
    key = hashlib.sha256(json.dumps(specs, sort_keys=True).encode()).hexdigest()[:12]
    native = work / f"native-{key}"
    run(
        "cmake",
        "-S",
        ROOT / "native",
        "-B",
        native,
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_CUDA_ARCHITECTURES={args.cuda_architectures}",
        f"-DCMAKE_PREFIX_PATH={';'.join(prefixes)}",
        f"-DHOLOLINK_SOURCE_DIR={hsb or ''}",
        f"-DPython_EXECUTABLE={sys.executable}",
    )
    run("cmake", "--build", native, "--target", "_hsb", "-j", args.jobs)
    extension = native / "_hsb.abi3.so"
    # Resolve SDK runtimes through the imported holoscan wheel in native and Docker installs.
    sdk_lib = Path(importlib.util.find_spec("holoscan").origin).parent / "lib"
    run(
        "patchelf",
        "--set-rpath",
        f"$ORIGIN/../../../holoscan/lib:{sdk_lib}:" + ":".join(f"{p}/lib" for p in prefixes),
        extension,
    )
    target = ROOT / "packages/runtime/src/telesurgery_runtime/backends/sdk5/_hsb.abi3.so"
    temporary = target.with_suffix(".so.tmp")
    shutil.copy2(extension, temporary)
    temporary.replace(target)
    print(f"SDK {hs.__version__} and IMX274 support installed for {sys.executable}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--dependencies", type=Path, default=ROOT / "dependencies/sdk5.toml")
    parser.add_argument("--cuda-architectures", default=os.environ.get("CUDAARCHS", "native"))
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if sys.version_info[:2] != (3, 12):
        parser.error("build with Python 3.12; wheels use its stable ABI")
    for program in ("git", "uv", "cmake", "ninja", "patchelf"):
        if not shutil.which(program):
            parser.error(f"missing {program}; run ./setup.sh")
    work = args.build.resolve()
    work.mkdir(parents=True, exist_ok=True)
    # Upstream validates patches in temporary non-Git copies below this checkout.
    os.environ["GIT_CEILING_DIRECTORIES"] = str(ROOT)
    specs = load(args.dependencies)
    for spec in specs.values():
        install(spec)
    sdk_spec = specs["holoscan"]
    prefixes = [
        str(Path(spec["prefix"]).expanduser().resolve())
        for spec in specs.values()
        if spec.get("prefix")
    ]
    prefixes += ["/opt/nvidia/holoscan", "/opt/nvidia/hololink"]
    if os.environ.get("CMAKE_PREFIX_PATH"):
        prefixes.extend(os.environ["CMAKE_PREFIX_PATH"].split(os.pathsep))
    if sdk_spec["provider"] == "git":
        prefixes.insert(0, str(build_holoscan(sdk_spec, work, args)))
    build_camera(specs, work, prefixes, args)


if __name__ == "__main__":
    main()
