# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read dependency providers and fetch sources without host-specific paths."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def load(path=ROOT / "dependencies/sdk5.toml"):
    specs = tomllib.loads(Path(path).read_text())
    for name in ("holoscan", "hololink"):
        spec = specs[name]
        if spec.get("provider") not in {"git", "packages", "installed"}:
            raise ValueError(f"{name}: provider must be git, packages, or installed")
        if spec["provider"] == "git" and not (spec.get("git") and spec.get("rev")):
            raise ValueError(f"{name}: git and rev are required")
        if spec["provider"] == "packages" and not (spec.get("pip") or spec.get("apt")):
            raise ValueError(f"{name}: packages requires a pip or apt list")
    return specs


def install(spec):
    if spec["provider"] != "packages":
        return
    missing = []
    for requirement in spec.get("apt", []):
        name, _, version = requirement.partition("=")
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${db:Status-Status} ${Version}", name],
            text=True,
            capture_output=True,
        )
        if result.returncode or not fnmatch.fnmatch(result.stdout, f"installed {version or '*'}"):
            missing.append(requirement)
    if missing:
        elevate = [] if os.geteuid() == 0 else ["sudo"]
        run(*elevate, "apt-get", "update")
        run(
            *elevate, "apt-get", "install", "-y", "--no-remove", "--no-install-recommends", *missing
        )
    if spec.get("pip"):
        run("uv", "pip", "install", "--python", sys.executable, *spec["pip"])


def prepare(sdk, environment):
    """The same uv workspace and build tools for native and container installations."""
    python = environment / "bin/python"
    if not python.exists():
        run("uv", "venv", "--python", "3.12", environment)
    run(
        "uv",
        "sync",
        "--all-packages",
        "--inexact",
        "--no-dev",
        "--extra",
        "codecs-cu13",
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(environment)},
        cwd=ROOT,
    )
    build_tools = (
        ["cmake>=4,<5", "patchelf", "nanobind==3.0.1", "cloudpickle", "pillow"]
        if sdk == "5"
        else ["cmake>=3.30,<4", "cuda-python>=13,<14"]
    )
    run("uv", "pip", "install", "--python", python, "ninja", *build_tools)


def checkout(name, spec, work):
    """Isolate each URL/revision so changing providers never resets someone else's tree."""
    key = hashlib.sha256(f"{spec['git']}@{spec['rev']}".encode()).hexdigest()[:12]
    target = work / "third_party" / f"{name}-{key}"
    if not (target / ".git").exists():
        run("git", "init", "-q", target)
    existing = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    if existing.returncode:
        run("git", "-C", target, "fetch", "--depth", "1", spec["git"], spec["rev"])
        run(
            "git",
            "-C",
            target,
            "checkout",
            "--detach",
            "FETCH_HEAD",
            env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        )
    actual = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True)
    fetched = subprocess.check_output(
        ["git", "-C", str(target), "rev-parse", "FETCH_HEAD"], text=True
    )
    revision = spec["rev"]
    pinned = len(revision) == 40 and all(c in "0123456789abcdefABCDEF" for c in revision)
    if actual != fetched or (pinned and actual.strip().lower() != revision.lower()):
        raise RuntimeError(f"{target}: unexpected checkout revision")
    for filename in spec.get("patches", []):
        patch = ROOT / filename
        applied = (
            subprocess.run(
                ["git", "-C", str(target), "apply", "--reverse", "--check", str(patch)],
                capture_output=True,
            ).returncode
            == 0
        )
        if not applied:
            run("git", "-C", target, "apply", patch)
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Prepare Python dependencies for native or Docker setup"
    )
    parser.add_argument("--sdk", choices=("4", "5"), default="5")
    parser.add_argument("--environment", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.sdk, args.environment.resolve())
