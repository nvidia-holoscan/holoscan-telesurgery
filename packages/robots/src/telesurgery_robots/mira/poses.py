# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor nominal arm pose and the application's physical jog limit, in degrees."""

MIRA_HOME = (15.7, 80.6, 45.0, 98.9)
MIRA_HOME_ROLL = 0.0
MIRA_HOME_GRIP = 0.0  # fraction of tool travel; zero is closed
MIRA_STEP_LIMIT = 1.0
MIRA_ROLL_LIMIT = 180.0  # application travel limit, not a vendor hardware rating


def roll_target(position, change):
    # Permit small inward steps if an external controller left the tool outside
    # our range; never snap an out-of-range measured pose to the limit.
    target = position + change
    if abs(position) > MIRA_ROLL_LIMIT:
        if abs(target) > abs(position):
            raise ValueError("Tool roll is outside the application's ±180° range")
        return target
    return max(-MIRA_ROLL_LIMIT, min(MIRA_ROLL_LIMIT, target))
