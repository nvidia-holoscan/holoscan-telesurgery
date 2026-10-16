# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rate-limited gripper targets, in fractions of travel, with a local input watchdog."""

import math
import time

GRIP_SPEED = {"min": 1, "max": 50, "default": 20}  # percent of travel per second
# Physical operating rate; simulation retains its configured jaw-drive limit.
PHYSICAL_GRIP_SPEED = {"min": 1, "max": 100, "default": 90}
GRIP_COUNTS = {"left": 1150.0, "right": 1350.0}  # vendor command scale, not installed jaw travel


def clamp(position):
    return max(0.0, min(1.0, position))


def opening_calibration(data=None):
    """Operator-confirmed jaw endpoints, independent of the vendor command scale."""
    if data is None:
        data = {}
    if not isinstance(data, dict) or set(data) - set(GRIP_COUNTS):
        raise ValueError("Gripper calibration must name left and/or right")
    result = {}
    for arm, maximum in GRIP_COUNTS.items():
        row = data.get(arm, {"closed": 0, "open": maximum})
        if not isinstance(row, dict) or set(row) not in (
            {"closed", "open"},
            {"closed", "open", "tolerance"},
        ):
            raise ValueError(
                "Gripper calibration requires closed/open counts and optional tolerance"
            )
        closed, opened, tolerance = row["closed"], row["open"], row.get("tolerance", 0)
        if (
            any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in (closed, opened, tolerance)
            )
            or not 0 <= closed < opened <= maximum
            or not 0 <= tolerance <= (opened - closed) * 0.05
        ):
            raise ValueError("Invalid gripper calibration counts or endpoint tolerance")
        result[arm] = {"closed": closed, "open": opened, "tolerance": tolerance}
    return result


def opening_position(counts, calibration):
    closed, opened = calibration["closed"], calibration["open"]
    tolerance = calibration["tolerance"]
    if counts <= closed + tolerance:
        return 0.0
    if counts >= opened - tolerance:
        return 1.0
    return (counts - closed) / (opened - closed)


def vendor_positions(joints):
    """Measured-position holds must use the API's count scale, never the display calibration."""
    return {arm: clamp(joints[arm][5] / maximum) for arm, maximum in GRIP_COUNTS.items()}


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
