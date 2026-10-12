# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Independently leased Versius simulation arms; no physical robot protocol."""

# The supplied BSU asset records its angular limits in degrees.
LIMITS = [
    (-180, 180),
    (-130, 90),
    (-180, 180),
    (-1, 170),
    (-190, 190),
    (-25, 28),
    (-80, 80),
    (-175, 190),
]
HOME = [0, -30, 0, 120, 0, 0, 0, 90]

# Three instrument bedside units and one visualisation bedside unit.
ARMS = {
    "left": "Left instrument",
    "right": "Right instrument",
    "assistant": "Assistant instrument",
    "endoscope": "Endoscope",
}
