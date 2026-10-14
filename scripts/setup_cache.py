# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reuse a successful native setup while its inputs and installed files are unchanged."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {"__pycache__", ".cache", ".git"}
BUILD_ENV = (
    "CC",
    "CXX",
    "CUDACXX",
    "CUDAHOSTCXX",
    "CUDAARCHS",
    "CUDA_HOME",
    "CUDA_PATH",
    "CFLAGS",
    "CXXFLAGS",
    "CPPFLAGS",
    "LDFLAGS",
    "CMAKE_ARGS",
    "CMAKE_PREFIX_PATH",
    "LD_LIBRARY_PATH",
    "PYTHONPATH",
    "CUDA_VISIBLE_DEVICES",
    "NVIDIA_VISIBLE_DEVICES",
    "TELESURGERY_SDK4_DEVELOPMENT",
    "TELESURGERY_FRANKA_PREFIX",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inventory(paths, *, contents=False):
    """Hash small source files; stat installed trees without reading large GPU libraries."""
    result = hashlib.sha256()
    visited = set()

    def visit(path):
        result.update(str(path).encode() + b"\0")
        if path.is_symlink():
            result.update(os.readlink(path).encode() + b"\0")
        try:
            info = path.stat()
        except FileNotFoundError:
            result.update(b"missing\0")
            return
        if path.is_dir():
            result.update(f"directory:{info.st_mode}\0".encode())
            identity = (info.st_dev, info.st_ino)
            if identity in visited:
                return
            visited.add(identity)
            for child in sorted(path.iterdir()):
                if child.name not in IGNORED and child.suffix not in {".pyc", ".pyo"}:
                    visit(child)
        elif contents:
            result.update(path.read_bytes())
        else:
            result.update(
                repr((info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)).encode()
            )
        result.update(b"\0")

    for path in sorted(set(paths)):
        visit(path)
    return result.hexdigest()


def inputs(root, sdk, franka):
    paths = [
        root / "setup.sh",
        root / "uv.lock",
        root / "pyproject.toml",
        root / "scripts/setup_cache.py",
        root / "scripts/setup_haply.py",
        root / "scripts/builders",
        root / "native",
        root / f"dependencies/sdk{sdk}.toml",
        root / "packages/core/src/telesurgery_core/video",
        root / "packages/app/src/telesurgery/__main__.py",
        root / "packages/app/src/telesurgery/application/cli.py",
    ]
    paths.extend(root.glob("packages/*/pyproject.toml"))
    if franka:
        paths.extend([root / "scripts/build_franka.sh", root / "packages/robots/native"])
    tools = []
    for name in ("uv", "nvcc", os.environ.get("CC", "cc"), os.environ.get("CXX", "c++")):
        resolved = shutil.which(name)
        if resolved:
            tools.append(Path(resolved))
    host = [Path("/etc/nv_tegra_release"), *tools]
    # Include both driver version and GPU identity, even when no build flags changed.
    gpu = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=uuid,name,driver_version", "--format=csv,noheader"],
        text=True,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    return digest(
        {
            "source": inventory(paths, contents=True),
            "host": inventory(host),
            "gpu": gpu,
            "platform": [platform.machine(), platform.release()],
            "environment": {key: os.environ.get(key) for key in BUILD_ENV},
        }
    )


def artifacts(root, sdk, workspace, franka):
    # This runs with the setup environment's Python 3.12, including on Ubuntu 22.04.
    import tomllib

    specs = tomllib.loads((root / f"dependencies/sdk{sdk}.toml").read_text())
    paths = [root / f".venv-sdk{sdk}", workspace / "sim-deps", Path("/var/lib/dpkg/status")]
    for name, spec in specs.items():
        if spec.get("provider") == "git":
            key = hashlib.sha256(f"{spec['git']}@{spec['rev']}".encode()).hexdigest()[:12]
            source = f"{name}-{key}"
            paths.extend([root / "build/third_party" / source, root / "build" / source / "install"])
            paths.extend(
                root / "build/third_party" / source / ".git" / ref for ref in ("HEAD", "FETCH_HEAD")
            )
        if spec.get("prefix"):
            paths.append(Path(spec["prefix"]).expanduser().resolve())
    paths.extend([Path("/opt/nvidia/holoscan"), Path("/opt/nvidia/hololink")])
    paths.extend(
        Path(p).resolve() for p in os.environ.get("CMAKE_PREFIX_PATH", "").split(os.pathsep) if p
    )
    if sdk == "5":
        paths.append(root / "packages/runtime/src/telesurgery_runtime/backends/sdk5/_hsb.abi3.so")
    else:
        paths.extend(
            [
                root / "build/hololink-install",
                Path(
                    os.environ.get(
                        "TELESURGERY_SDK4_DEVELOPMENT", root / "build/third_party/sdk4-development"
                    )
                ),
            ]
        )
    if franka:
        operator = os.environ.get("SUDO_USER") or os.environ.get("USER")
        paths.extend(
            [
                root / "build/third_party/libfranka-d053f51c209c",
                Path(os.environ.get("TELESURGERY_FRANKA_PREFIX", root / "build/franka/install")),
                root / "packages/robots/src/telesurgery_robots/franka",
                Path(f"/etc/security/limits.d/90-telesurgery-franka-{operator}.conf"),
            ]
        )
    return inventory(paths)


def stamp_path(root, sdk, workspace, franka):
    key = digest([str(root), sdk, str(workspace), franka])[:16]
    return root / "build/setup" / f"{key}.json"


def check(root, sdk, workspace, franka, pending, *, force=False):
    stamp = stamp_path(root, sdk, workspace, franka)
    try:
        current = inputs(root, sdk, franka)
        pending.write_text(current)
        saved = json.loads(stamp.read_text()) if stamp.exists() else {}
        if (
            not force
            and isinstance(saved, dict)
            and saved.get("inputs") == current
            and (root / f".venv-sdk{sdk}/bin/python").exists()
            and saved.get("artifacts") == artifacts(root, sdk, workspace, franka)
        ):
            return True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Setup cache unavailable; running setup ({exc}).")
    # A failed or interrupted rebuild must not leave an older successful stamp trusted.
    stamp.unlink(missing_ok=True)
    return False


def record(root, sdk, workspace, franka, pending):
    stamp = stamp_path(root, sdk, workspace, franka)
    try:
        current = inputs(root, sdk, franka)
        if pending.read_text() != current:
            print("Setup inputs changed during installation; the next run will recheck them.")
            return
        saved = {"inputs": current, "artifacts": artifacts(root, sdk, workspace, franka)}
        stamp.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=stamp.parent, delete=False) as output:
            json.dump(saved, output)
        Path(output.name).replace(stamp)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Setup completed without saving its cache ({exc}).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "record"))
    parser.add_argument("--sdk", choices=("4", "5"), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--pending", type=Path, required=True)
    parser.add_argument("--franka", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    parameters = (ROOT, args.sdk, args.workspace.resolve(), args.franka, args.pending)
    if args.action == "check":
        return 0 if check(*parameters, force=args.force) else 1
    record(*parameters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
