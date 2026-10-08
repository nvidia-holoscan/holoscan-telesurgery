# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Quick platform check before offering Isaac Sim on a node."""

import platform
import re
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def simulation_support():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        gpu = result.stdout.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        return {"supported": False, "reason": "No accessible NVIDIA GPU"}
    machine = platform.machine()
    if machine == "aarch64":
        supported = gpu == "NVIDIA GB10"
        reason = "Isaac Sim on ARM is supported on DGX Spark only"
    else:
        supported = machine == "x86_64" and bool(
            "RTX" in gpu or re.fullmatch(r"NVIDIA (A10G?|A40|L4|L40S?)", gpu)
        )
        reason = "Isaac Sim requires an RTX-capable NVIDIA GPU on x86"
    return {"supported": supported, "reason": "" if supported else reason}


if __name__ == "__main__":
    import json

    print(json.dumps(simulation_support()))
