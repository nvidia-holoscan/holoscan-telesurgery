# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Require SPDX metadata, except for the exact Blossom vendor template."""

import hashlib
import sys
from pathlib import Path

# Blossom rejects workflows that do not match a supported template. Preserve its
# full Apache-2.0 notice; permit only this reviewed template, not arbitrary edits.
BLOSSOM_TEMPLATE = Path(".github/workflows/blossom-ci.yml")
BLOSSOM_SHA256 = "f8d76badb269f1531f69f0816587fa78436c68b40fc00ac2e2c51b4a9ad0b6b7"


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
