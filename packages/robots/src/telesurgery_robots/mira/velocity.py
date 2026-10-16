# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Locally paced joint velocity input with finite lead and a fresh-input watchdog."""

import math

from ruckig import (
    ControlInterface,
    InputParameter,
    OutputParameter,
    Result,
    Ruckig,
    Synchronization,
)
from telesurgery_robots.adapters.base import values
from telesurgery_robots.mira.cartesian import JOINT_LIMITS

# Operating envelopes, not a claim about the motors' rated maximum velocity.
PHYSICAL = {"arm_deg_s": 20.0, "roll_deg_s": 40.0}
SIMULATION = {"arm_deg_s": 30.0, "roll_deg_s": 100.0}


def command(data, rates):
    if not isinstance(data, dict) or set(data) != {"left", "right"}:
        raise ValueError("Joint velocity input requires both MIRA arms")
    result = {}
    for arm in ("left", "right"):
        row = values(data[arm], 5, math.inf)
        if any(abs(v) > rates["arm_deg_s"] for v in row[:4]) or abs(row[4]) > rates["roll_deg_s"]:
            raise ValueError("MIRA joint velocity exceeds the configured operating limit")
        result[arm] = row
    return result


class JointVelocity:
    """Integrate only the newest rate; an obstruction cannot accumulate travel."""

    def __init__(self, rates, *, lead=1.0, roll_lead=None):
        self.rates, self.lead = rates, lead
        self.roll_lead = lead if roll_lead is None else roll_lead
        self.clear()

    def clear(self):
        self.active = False
        self.updated = self.deadline = 0.0
        self.input = self.output = self.generator = None
        self.roll = False

    def request(self, data, measured, now):
        data = command(data, self.rates)
        if not self.active:
            self.generator = Ruckig(10, 0.01)
            self.input, self.output = InputParameter(10), OutputParameter(10)
            self.input.control_interface = ControlInterface.Velocity
            self.input.synchronization = Synchronization.No
            self.input.current_position = [
                v for arm in ("left", "right") for v in measured[arm][:5]
            ]
            self.input.current_velocity = [0.0] * 10
            self.input.current_acceleration = [0.0] * 10
            maximum = ([self.rates["arm_deg_s"]] * 4 + [self.rates["roll_deg_s"]]) * 2
            self.input.max_velocity = maximum
            self.input.max_acceleration = [v * 4 for v in maximum]
            self.input.max_jerk = [v * 40 for v in maximum]
            self.updated = now
        self.input.target_velocity = [v for arm in ("left", "right") for v in data[arm]]
        self.input.target_acceleration = [0.0] * 10
        self.roll |= any(data[arm][4] for arm in data)
        self.active, self.deadline = True, now + 0.2

    def advance(self, measured, now, limits=None):
        if not self.active:
            return None
        if now >= self.deadline or now - self.updated >= 0.2:
            self.clear()
            return {arm: list(row) for arm, row in measured.items()}
        elapsed = now - self.updated
        if elapsed < 0.001:
            return None
        self.updated = now
        # A late local tick never catches up with a burst of old motion.
        self.generator.delta_time = min(elapsed, 0.02)
        result = self.generator.update(self.input, self.output)
        if result < Result.Working:
            raise RuntimeError("MIRA joint trajectory calculation failed")
        target = {arm: list(row) for arm, row in measured.items()}
        position = list(self.output.new_position)
        velocity = list(self.output.new_velocity)
        acceleration = list(self.output.new_acceleration)
        for a, arm in enumerate(("left", "right")):
            bounds = [*(limits[arm] if limits else JOINT_LIMITS), (-180.0, 180.0)]
            for j in range(5):
                i = a * 5 + j
                actual = measured[arm][j]
                lo, hi = bounds[j]
                # Permit retreat if external control left a joint outside its
                # nominal range, without snapping it back to the boundary.
                lead = self.roll_lead if j == 4 else self.lead
                lower = max(actual - lead, min(actual, lo))
                upper = min(actual + lead, max(actual, hi))
                bounded = max(lower, min(upper, position[i]))
                # Feedback lag limits position lead, not the requested rate.
                # Restarting the ramp at every lead clamp causes repeated tiny
                # accelerations (notably with quantized tool-roll feedback).
                # Reset only at a mechanical boundary in the outward direction.
                if (position[i] <= min(actual, lo) and velocity[i] < 0) or (
                    position[i] >= max(actual, hi) and velocity[i] > 0
                ):
                    velocity[i] = acceleration[i] = 0.0
                position[i] = target[arm][j] = bounded
        self.input.current_position = position
        self.input.current_velocity = velocity
        self.input.current_acceleration = acceleration
        return target
