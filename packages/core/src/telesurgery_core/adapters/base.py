# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Captured frame and its timing metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CameraSample:
    """Owned, ready BGR8 NumPy/CuPy pixels and a host Unix timestamp.

    A GPU producer must complete its writes before returning; pixels remain valid
    until the sample is released. read() returns None when no new frame is ready.
    """

    image: object
    captured_ns: int
    sim_command_sequence: int = -1
    started_ns: int = 0  # Buffer handoff on the local monotonic clock; 0: read return, -1: unknown.
