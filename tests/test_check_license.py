# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The vendor exception must not admit edits or unlicensed project files."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ".github/workflows/blossom-ci.yml"
SPDX = (
    "# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.\n"
    "# SPDX-License-Identifier: Apache-2.0\n"
)


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("example.py", SPDX + "print('hello')\n", 0),
        ("example.py", "print('hello')\n", 1),
        (TEMPLATE, (ROOT / TEMPLATE).read_text(), 0),
        (TEMPLATE, (ROOT / TEMPLATE).read_text() + "# changed\n", 1),
        (TEMPLATE, SPDX + (ROOT / TEMPLATE).read_text(), 1),
        ("other.yml", (ROOT / TEMPLATE).read_text(), 1),
    ],
)
def test_license_policy(tmp_path, name, content, expected):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_license.py"), name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
