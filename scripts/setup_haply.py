#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Install the pinned Haply service, or extract it for the Docker runtime."""

import argparse
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "3.5.6"
CDN = "https://cdn.haply.co/r/38736259"


def package_name(system, machine):
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine)
    ubuntu = system.get("VERSION_ID", "").replace(".", "")
    if system.get("ID") != "ubuntu" or ubuntu not in {"2204", "2404"} or not arch:
        raise ValueError("Haply service requires Ubuntu 22.04/24.04 on x86_64 or aarch64.")
    return f"haply-inverse-service-ubuntu{ubuntu}-{arch}-{VERSION}.deb"


def install(extract=None):
    if extract is None:
        installed = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version} ${db:Status-Status}", "haply-inverse-service"],
            capture_output=True,
            text=True,
        )
        if installed.returncode == 0 and installed.stdout.strip() == f"{VERSION} installed":
            return
    package = package_name(platform.freedesktop_os_release(), platform.machine())
    with tempfile.TemporaryDirectory(prefix="telesurgery-haply-") as temporary:
        directory = Path(temporary)
        archive = directory / package
        print(f"Downloading Haply Inverse Service {VERSION}…", flush=True)
        with urlopen(f"{CDN}/{package}", timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        if extract:
            root = directory / "root"
            subprocess.run(["dpkg-deb", "--extract", str(archive), str(root)], check=True)
            destination = Path(extract)
            destination.mkdir(parents=True, exist_ok=True)
            binary = destination / "haply-inverse-service"
            shutil.copy2(root / "usr/bin/haply-inverse-service", binary)
            subprocess.run(["strip", str(binary)], check=True)
            shutil.copytree(
                root / "usr/share/doc/haply-inverse-service",
                destination / "doc",
                dirs_exist_ok=True,
            )
        else:
            # The vendor package supplies udev rules and a systemd service that owns USB access.
            # apt's unprivileged downloader needs to traverse the temporary directory.
            directory.chmod(0o755)
            elevate = [] if os.geteuid() == 0 else ["sudo"]
            subprocess.run(
                [*elevate, "apt-get", "install", "-y", "--no-remove", str(archive)], check=True
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", metavar="DIRECTORY", help="Extract without host installation")
    args = parser.parse_args()
    install(args.extract)
