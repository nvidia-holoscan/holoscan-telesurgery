# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Latest-pose following for the scaled MIRA simulation, driven on the patient."""

import logging
import math

import numpy as np
from telesurgery_robots.adapters.base import values

FOLLOW = {"version": 1, "linear_speed_mm_s": 1500.0, "joint_speed_deg_s": 180.0}
LOG = logging.getLogger(__name__)


def command(data):
    if not isinstance(data, dict) or set(data) != {
        "arm",
        "pose",
        "arm_percent",
        "roll_percent",
        "id",
    }:
        raise ValueError("MIRA following requires an arm, tool pose, speeds and target id")
    if not isinstance(data["arm"], str) or data["arm"] not in {"left", "right"}:
        raise ValueError("Unknown MIRA arm")
    pose = values(data["pose"], 5, 2500)
    if any(abs(v) > 180 for v in pose[3:]):
        raise ValueError("MIRA tool angles must be between -180 and 180 degrees")
    for key in ("arm_percent", "roll_percent"):
        v = data[key]
        if type(v) not in (int, float) or not math.isfinite(v) or not 1 <= v <= 100:
            raise ValueError("MIRA following speed must be between 1 and 100 percent")
    if type(data["id"]) is not int or data["id"] < 0:
        raise ValueError("Invalid MIRA target id")
    return {**data, "pose": pose}


class Follow:
    """Bound each local servo step, retaining no queue of remote hand positions."""

    def __init__(self, arm, measured, now):
        self.arm = arm
        self.position = np.asarray(measured[:5], dtype=float).copy()
        self.velocity = np.zeros(5)
        self.target = None
        self.limited = False
        self.error = ""
        self.progress = np.asarray(measured[:5], dtype=float).copy()
        self.advanced = now

    def request(self, target):
        self.target = target

    def advance(self, data, dt, now):
        measured, pose, jacobian, limits = data
        measured = np.asarray(measured[:5], dtype=float)
        pending = np.max(np.abs(self.position - measured)) > 0.2
        if not pending or np.max(np.abs(measured - self.progress)) > 0.02:
            self.progress, self.advanced = measured.copy(), now
        if pending and now - self.advanced > 0.75:
            lag = np.abs(self.position - measured)
            joint = int(np.argmax(lag))
            if not self.error:
                self.error = (
                    f"MIRA tool tracking error ({self.arm} J{joint + 1}: "
                    f"{lag[joint]:.2f} degrees behind, no joint progress for "
                    f"{now - self.advanced:.2f} s); release input before retrying"
                )
                LOG.warning(
                    "%s; target=%s; commanded_joints_deg=%s; measured_joints_deg=%s",
                    self.error,
                    self.target,
                    np.round(self.position, 3).tolist(),
                    np.round(measured, 3).tolist(),
                )
            return measured.copy()
        if dt <= 0 or self.target is None:
            return self.position
        target = np.asarray(self.target["pose"])
        arm_speed = self.target["arm_percent"] / 100
        roll_speed = self.target["roll_percent"] / 100
        # Solve against the unfinished command, not the delayed measured pose.
        lead = self.position[:4] - measured[:4]
        planned = pose + jacobian @ lead
        error = target[:4] - planned
        error[3] = (error[3] + 180) % 360 - 180
        change = error * min(1, dt / 0.05)
        scale = max(
            1,
            np.linalg.norm(change[:3]) / (FOLLOW["linear_speed_mm_s"] * arm_speed * dt),
            abs(change[3]) / (120 * arm_speed * dt),
        )
        change /= scale
        joints = np.linalg.lstsq(jacobian, change, rcond=1e-3)[0]
        requested = np.r_[
            joints / dt,
            np.clip((target[4] - self.position[4]) / 0.05, -180 * roll_speed, 180 * roll_speed),
        ]
        requested[:4] /= max(
            1, np.max(np.abs(requested[:4])) / (FOLLOW["joint_speed_deg_s"] * arm_speed)
        )
        # Brake before mechanical limits; limits and the measured lead envelope
        # still take precedence if contact makes the requested ramp impossible.
        bounds = np.asarray([*limits, (-180, 180)], dtype=float)
        acceleration = np.r_[np.full(4, 720 * arm_speed), 720 * roll_speed]
        room = np.where(requested >= 0, bounds[:, 1] - self.position, self.position - bounds[:, 0])
        braking = np.sqrt(2 * acceleration * np.maximum(0, room))
        requested = np.clip(requested, -braking, braking)
        self.velocity += np.clip(requested - self.velocity, -acceleration * dt, acceleration * dt)
        step = self.velocity * dt
        fractions = np.ones(5)
        self.limited = False
        for index, (old, actual, movement, (lo, hi)) in enumerate(
            zip(self.position, measured, step, bounds, strict=True)
        ):
            if movement > 0:
                fractions[index] = min(1, (min(hi, actual + 3) - old) / movement)
            elif movement < 0:
                fractions[index] = min(1, (max(lo, actual - 3) - old) / movement)
        fractions = np.maximum(0, fractions)
        # XYZ and tilt share a kinematic path; axial roll is independent.
        # Contact can deflect roll outside its lead envelope. Keep its command
        # bounded without preventing the tool from lifting away from contact.
        fractions[:4] = np.min(fractions[:4])
        # A saturated desired direction is an ordinary workspace boundary.
        desired = np.r_[joints, target[4] - self.position[4]]
        self.limited = bool(
            np.any(
                ((self.position >= bounds[:, 1] - 0.05) & (desired > 1e-4))
                | ((self.position <= bounds[:, 0] + 0.05) & (desired < -1e-4))
            )
        )
        if np.linalg.norm(jacobian @ joints - change) > 0.1:
            self.limited = True
        tool_lead = jacobian @ (lead + step[:4] * fractions[:4])
        distance = np.linalg.norm(tool_lead[:3])
        if distance > 15 and distance >= np.linalg.norm((jacobian @ lead)[:3]):
            # Let physics catch up without accumulating deferred travel.
            # If contact displaced the tool outside the envelope, allow a
            # retreat that reduces the lead instead of trapping it there.
            fractions[:4] = 0.0
        self.position += step * fractions
        self.velocity *= fractions
        self.position = np.clip(self.position, bounds[:, 0], bounds[:, 1])
        return self.position
