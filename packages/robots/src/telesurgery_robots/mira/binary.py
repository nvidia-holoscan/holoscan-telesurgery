# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Install the local vendor executable without running or downloading it."""

import hashlib
import os
import platform
import shutil
import tempfile
from pathlib import Path


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def install(workspace, source):
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("MIRA API must be a Linux executable file")
    machine = platform.machine().lower()
    architectures = {"aarch64": 183, "arm64": 183, "x86_64": 62, "amd64": 62}
    if machine not in architectures:
        raise ValueError(f"MIRA API does not support this architecture: {machine}")
    with source.open("rb") as stream:
        header = stream.read(64)
    if (
        len(header) < 64
        or header[:7] != b"\x7fELF\x02\x01\x01"
        or int.from_bytes(header[16:18], "little") not in {2, 3}
        or int.from_bytes(header[18:20], "little") != architectures[machine]
    ):
        raise ValueError(f"MIRA API must be a Linux {machine} ELF executable")
    digest = checksum(source)
    destination = workspace / "mira-api"
    workspace.mkdir(parents=True, exist_ok=True)
    if source != destination or not os.access(destination, os.X_OK):
        with tempfile.TemporaryDirectory(dir=workspace) as staging:
            staged = Path(staging) / "mira-api"
            shutil.copyfile(source, staged)
            if checksum(staged) != digest:
                raise ValueError("MIRA API changed during installation; try again")
            staged.chmod(0o700)
            os.replace(staged, destination)
    return {"executable": "mira-api", "sha256": digest}
