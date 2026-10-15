#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reuse Haply Hub, install the pinned service, or extract it for the Docker runtime."""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "3.5.6"
CDN = "https://cdn.haply.co/r/38736259"
# Hashes of the vendor packages downloaded over HTTPS from the release links at
# https://develop.haply.co/releases/installer/3.5.6 (Ubuntu 22.04/24.04, amd64/arm64).
DIGESTS = {
    "haply-inverse-service-ubuntu2204-amd64-3.5.6.deb": (
        "729de2d43c37e57ef1c0c1db7767a39451c61d9ef55379c2755c1c39f0129d7c"
    ),
    "haply-inverse-service-ubuntu2204-arm64-3.5.6.deb": (
        "b399266b1dc0561b87666677eb3150a5c053ca2a0230be7b1d588a4ad1c275eb"
    ),
    "haply-inverse-service-ubuntu2404-amd64-3.5.6.deb": (
        "4d13c2373c6f2878959a9de9348127a0077355590f52a5b6fb8a5332c9a2bed1"
    ),
    "haply-inverse-service-ubuntu2404-arm64-3.5.6.deb": (
        "2b582d3a2917d1dc40e09e07b153fac8549e661556dd2c3c19e86c1c42258d78"
    ),
}


def package_name(system, machine):
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine)
    ubuntu = system.get("VERSION_ID", "").replace(".", "")
    if system.get("ID") != "ubuntu" or ubuntu not in {"2204", "2404"} or not arch:
        raise ValueError(
            "The standalone Haply package requires Ubuntu 22.04/24.04 on x86_64 or aarch64. "
            "For native setup on other releases, including Ubuntu 26.04, install Haply Hub."
        )
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
        hub = subprocess.run(
            ["dpkg-query", "-W", "-f=${db:Status-Status}", "haply-hub"],
            capture_output=True,
            text=True,
        )
        if hub.returncode == 0 and hub.stdout.strip() == "installed":
            print("Using installed Haply Hub; keep it open on the surgeon host for Haply input.")
            return
    package = package_name(platform.freedesktop_os_release(), platform.machine())
    expected = DIGESTS.get(package)
    if not expected:
        raise ValueError(f"Unrecognized Haply package: {package}")
    with tempfile.TemporaryDirectory(prefix="telesurgery-haply-") as temporary:
        directory = Path(temporary)
        archive = directory / package
        print(f"Downloading Haply Inverse Service {VERSION}…", flush=True)
        # Fixed HTTPS origin and allowlisted package; verify bytes before executing or extracting.
        with urlopen(f"{CDN}/{package}", timeout=60) as response:  # nosec B310
            with archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        with archive.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Haply package digest mismatch: {package}")
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
