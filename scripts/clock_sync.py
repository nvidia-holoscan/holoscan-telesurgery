#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Configure a host chrony server or client without stepping the system clock."""

import argparse
import ipaddress
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def configuration(server, allow):
    if server:
        if not re.fullmatch(r"[A-Za-z0-9.:-]+", server):
            raise ValueError("Use a time server IP address or DNS name")
        source = f"server {server} iburst xleave minpoll 0 maxpoll 4"
    else:
        source = "pool ntp.ubuntu.com iburst maxsources 4"
    lines = [
        "# Managed by Holoscan Telesurgery clock_sync.py",
        source,
        "driftfile /var/lib/chrony/chrony.drift",
        "rtcsync",
        "maxslewrate 100",
        "leapsecmode slew",
        "bindcmdaddress 127.0.0.1",
        "bindcmdaddress ::1",
        "cmdport 323",
    ]
    if allow:
        lines.append(f"allow {ipaddress.ip_network(allow, strict=False)}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    roles = parser.add_mutually_exclusive_group()
    roles.add_argument("--server", metavar="ROOM_SUBNET", help="Serve NTP to this subnet only")
    roles.add_argument("--client", metavar="TIME_SERVER", help="Synchronize to this NTP server")
    args = parser.parse_args()
    content = configuration(args.client, args.server)

    def active(name):
        return (
            subprocess.run(
                ["systemctl", "is-active", "--quiet", name], stderr=subprocess.DEVNULL
            ).returncode
            == 0
        )

    target = Path("/etc/chrony/chrony.conf")
    if active("chrony") and (
        not (args.client or args.server) or (target.exists() and target.read_text() == content)
    ):
        print("Using the existing chrony configuration.")
        return
    for name in ("ptp4l", "phc2sys", "ntp", "ntpsec"):
        if active(name):
            if args.client or args.server:
                parser.error(f"{name} is active; preserve its clock configuration")
            print(f"Preserving the existing {name} clock service.")
            return
    if os.geteuid() != 0:
        print("Setting up the host clock service; sudo is needed once.", flush=True)
        if (
            not sys.stdin.isatty()
            and subprocess.run(["sudo", "-n", "true"], stderr=subprocess.DEVNULL).returncode
        ):
            print(
                "Clock setup needs an interactive ./setup.sh on this host. "
                "Streaming remains available; cross-host clock quality will be unavailable."
            )
            return
        subprocess.run(
            ["sudo", sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], check=True
        )
        return

    def run(*args):
        subprocess.run(args, check=True)

    installed = shutil.which("chronyd") is not None
    if not installed:
        # Package installation must not start the default configuration's makestep rule.
        run("systemctl", "mask", "--runtime", "chrony.service")
    try:
        if not installed:
            run("apt-get", "update")
            run("apt-get", "install", "-y", "chrony")
        # Ubuntu's chrony AppArmor policy only allows configuration in this directory.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", dir=target.parent) as candidate:
            candidate.write(content)
            candidate.flush()
            os.chmod(candidate.name, 0o644)
            subprocess.run(
                ["chronyd", "-p", "-f", candidate.name], check=True, stdout=subprocess.DEVNULL
            )
        backup = target.with_suffix(".conf.before-telesurgery")
        if target.exists() and not backup.exists():
            shutil.copy2(target, backup)
        target.write_text(content)
        subprocess.run(["systemctl", "disable", "--now", "systemd-timesyncd"], check=False)
    finally:
        if not installed:
            run("systemctl", "unmask", "--runtime", "chrony.service")
    run("systemctl", "enable", "chrony.service")
    run("systemctl", "restart", "chrony.service")
    print("Chrony configured with gradual corrections. Check convergence: chronyc tracking")
    print(f"Previous configuration: {backup}")


if __name__ == "__main__":
    main()
