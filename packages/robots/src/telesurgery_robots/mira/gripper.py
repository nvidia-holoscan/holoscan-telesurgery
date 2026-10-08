# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rate-limited gripper targets, in fractions of travel, with a local input watchdog."""

import math
import time

GRIP_SPEED = {"min": 1, "max": 50, "default": 20}  # percent of travel per second
GRIP_COUNTS = {"left": 1150.0, "right": 1350.0}  # supplied vendor API tool-drive ranges


def clamp(position):
    return max(0.0, min(1.0, position))


def gripper_rates(command, grippers):
    if not isinstance(command, dict) or set(command) != {"velocity"}:
        raise ValueError("Gripper control requires held input; refresh the dashboard")
    rates = command["velocity"]
    if not isinstance(rates, dict) or not rates or set(rates) - set(grippers):
        raise ValueError("Unknown gripper")
    for rate in rates.values():
        if (
            type(rate) not in (int, float)
            or not math.isfinite(rate)
            or abs(rate) > GRIP_SPEED["max"] / 100
        ):
            raise ValueError("Invalid gripper speed")
    return rates


class GripperJog:
    def __init__(self):
        self.rates, self.targets, self.deadlines = {}, {}, {}
        self.updated = time.monotonic()

    def command(self, rates, measured):
        now = time.monotonic()
        if not self.rates:
            self.updated = now
        for arm, rate in rates.items():
            if not rate and arm not in self.rates:
                continue
            self.targets.setdefault(arm, clamp(measured[arm]))
            self.rates[arm], self.deadlines[arm] = rate, now + 0.2

    def advance(self, measured):
        now = time.monotonic()
        elapsed = max(0, min(now - self.updated, 0.1))
        self.updated = now
        targets = {}
        for arm, rate in list(self.rates.items()):
            if not rate or now >= self.deadlines[arm]:
                targets.update(self.stop(measured, arm))
                continue
            # Never leave a distant target waiting behind a stalled tool.
            lead = abs(rate) * 0.1
            target = clamp(self.targets[arm] + rate * elapsed)
            target = max(clamp(measured[arm] - lead), min(clamp(measured[arm] + lead), target))
            if target != self.targets[arm]:
                self.targets[arm] = targets[arm] = target
        return targets

    def stop(self, measured, arm=None):
        targets = {}
        for key in list(self.rates) if arm is None else [arm]:
            if key not in self.rates:
                continue
            targets[key] = clamp(measured[key])
            del self.rates[key], self.targets[key], self.deadlines[key]
        return targets

    def clear(self):
        self.rates.clear()
        self.targets.clear()
        self.deadlines.clear()
