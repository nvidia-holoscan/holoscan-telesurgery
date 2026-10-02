# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Require SPDX metadata in the leading header of project source files."""

import sys
from pathlib import Path


def main():
    failed = False
    for name in sys.argv[1:]:
        header = "\n".join(Path(name).read_text().splitlines()[:12])
        if (
            "SPDX-FileCopyrightText:" not in header
            or "SPDX-License-Identifier: Apache-2.0" not in header
        ):
            print(f"{name}: missing Apache-2.0 SPDX license/copyright header")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
