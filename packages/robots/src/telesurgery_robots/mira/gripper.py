# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rate-limited gripper targets, in fractions of travel, with a local input watchdog."""

import math
import time

GRIP_SPEED = {"min": 1, "max": 50, "default": 20}  # percent of travel per second
# Physical operating rate; simulation retains its configured jaw-drive limit.
PHYSICAL_GRIP_SPEED = {"min": 1, "max": 100, "default": 90}
GRIP_COUNTS = {"left": 1150.0, "right": 1350.0}  # supplied vendor API tool-drive ranges


def clamp(position):
    return max(0.0, min(1.0, position))


def gripper_rates(command, grippers, limits=GRIP_SPEED):
    if not isinstance(command, dict) or set(command) != {"velocity"}:
        raise ValueError("Gripper control requires held input; refresh the dashboard")
    rates = command["velocity"]
    if not isinstance(rates, dict) or not rates or set(rates) - set(grippers):
        raise ValueError("Unknown gripper")
    for rate in rates.values():
        if (
            type(rate) not in (int, float)
            or not math.isfinite(rate)
            or abs(rate) > limits["max"] / 100
        ):
            raise ValueError("Invalid gripper speed")
    return rates


class GripperJog:
    def __init__(self, *, retain_closing_load=False):
        self.rates, self.targets, self.deadlines = {}, {}, {}
        self.retain_closing_load = retain_closing_load
        self.updated = time.monotonic()

    def command(self, rates, measured):
        now = time.monotonic()
        if not self.rates:
            self.updated = now
        for arm, rate in rates.items():
            if not rate:
                if arm in self.rates:
                    # Stop on the next physics update while retaining the last
                    # direction, just as releasing the controller does.
                    self.deadlines[arm] = now
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
            # A position-driven simulated jaw needs its small closing lead to
            # retain contact force after button release. The lead was already
            # bounded to 100 ms of travel; never continue an opening command.
            targets[key] = clamp(
                min(measured[key], self.targets[key])
                if self.retain_closing_load and self.rates[key] < 0
                else measured[key]
            )
            del self.rates[key], self.targets[key], self.deadlines[key]
        return targets

    def clear(self):
        self.rates.clear()
        self.targets.clear()
        self.deadlines.clear()
