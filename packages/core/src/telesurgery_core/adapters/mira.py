# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA simulation commands."""

from __future__ import annotations

import math


def delta(left, right) -> dict:
    for arm in (left, right):
        if len(arm) != 4 or any(not math.isfinite(v) or abs(v) > 5 for v in arm):
            raise ValueError("expected four bounded deltas per arm")
    return {
        "jsonrpc": "2.0",
        "method": "set_mira_cartesian_delta",
        "params": {"left": list(left), "right": list(right)},
    }
