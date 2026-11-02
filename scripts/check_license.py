# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Require SPDX metadata, except for the reviewed Blossom workflow."""

import hashlib
import sys
from pathlib import Path

# Blossom validates workflows against supported templates. Preserve the vendor's
# full Apache-2.0 notice; permit only the reviewed workflow with pinned actions.
BLOSSOM_TEMPLATE = Path(".github/workflows/blossom-ci.yml")
BLOSSOM_SHA256 = "db3ae7177f667063b126f75a9ac7bf20b0d3cd9caf49589e944aea47bca6977e"


def main():
    failed = False
    for name in sys.argv[1:]:
        path = Path(name)
        if path == BLOSSOM_TEMPLATE:
            if hashlib.sha256(path.read_bytes()).hexdigest() != BLOSSOM_SHA256:
                print(f"{name}: changed Blossom template; review checksum and security exceptions")
                failed = True
            continue
        header = "\n".join(path.read_text().splitlines()[:12])
        if (
            "SPDX-FileCopyrightText:" not in header
            or "SPDX-License-Identifier: Apache-2.0" not in header
        ):
            print(f"{name}: missing Apache-2.0 SPDX license/copyright header")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
