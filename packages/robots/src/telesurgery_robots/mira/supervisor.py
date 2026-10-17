# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exit the vendor process when its owning node stops renewing its lease.

Process termination is not a hardware emergency stop or proof of motor power-off.
"""

import signal
import subprocess
import sys
import time
from pathlib import Path

LEASE_SECONDS = 3


def fresh(path, now=None):
    try:
        age = (time.monotonic() if now is None else now) - float(path.read_text())
        return 0 <= age < LEASE_SECONDS
    except (OSError, ValueError):
        return False


def supervise(path, command):
    if not fresh(path):
        raise RuntimeError("MIRA node lease is missing or expired; vendor API was not started")
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, stop)
    process = subprocess.Popen(command)
    try:
        while process.poll() is None:
            if stopped or not fresh(path):
                print(
                    "MIRA node lease ended; terminating vendor API. Physical stop is unconfirmed.",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
            time.sleep(0.1)
        return process.returncode
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(supervise(Path(sys.argv[1]), sys.argv[2:]))
