# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Simulation drive targets: planned Franka motion and MIRA joint-space demonstration."""

from __future__ import annotations

import time

from telesurgery_robots.adapters.base import speed_value, values
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED
from telesurgery_robots.franka.trajectory import JointTrajectory
from telesurgery_robots.mira.gripper import GripperJog, clamp, gripper_rates
from telesurgery_robots.mira.poses import MIRA_HOME, roll_target


class SimRobot:
    # LJ6_1_joint and RJ6_joint limits in the MIRA USD; the jaws are mirrored.
    gripper_ranges = {"left": (0.3, 40.0), "right": (-0.1, -40.0)}

    def __init__(self, environment="mira"):
        self.pose = {
            arm: [*MIRA_HOME, 0.0, limits[0]] for arm, limits in self.gripper_ranges.items()
        }
        if environment == "franka":
            self.pose = {"joints": list(FRANKA_HOME)}
        self.trajectory = None
        self.mode = None
        self.speed = FRANKA_SPEED["default"]
        self.updated = time.monotonic()
        self.deadline = 0.0
        self.feedback = {}
        self.grip = GripperJog()

    def _grippers(self):
        return {
            arm: clamp(
                (self.feedback.get("grippers_deg", {}).get(arm, self.pose[arm][5]) - closed)
                / (opened - closed)
            )
            for arm, (closed, opened) in self.gripper_ranges.items()
        }

    def _grip_targets(self, targets):
        for arm, position in targets.items():
            closed, opened = self.gripper_ranges[arm]
            self.pose[arm][5] = closed + position * (opened - closed)

    def advance(self, now=None):
        now = time.monotonic() if now is None else now
        elapsed = max(0, min(now - self.updated, 0.1))
        self.updated = now
        if "left" in self.pose:
            self._grip_targets(self.grip.advance(self._grippers()))
        if self.trajectory is None or elapsed <= 0:
            return
        if now > self.deadline and self.mode == "jog":
            self._stop()
        self.pose["joints"] = self.trajectory.advance(elapsed)
        if self.trajectory.finished:
            self.trajectory = self.mode = None

    def _stop(self):
        if self.trajectory:
            self.trajectory.stop()
            self.mode = "stopping"

    def _state(self):
        return {
            "targets_deg": {arm: list(pose) for arm, pose in self.pose.items()},
            "acknowledgement": "controller target accepted",
            **self.feedback,
            **(
                {
                    "control_active": self.trajectory is not None,
                    "home_active": self.mode == "home",
                    "stopping": self.mode == "stopping",
                }
                if "joints" in self.pose
                else {"grippers": self._grippers(), "control_active": bool(self.grip.rates)}
            ),
        }

    def _target(self, goal, mode, speed):
        if self.trajectory is not None and (
            self.mode not in {"step", "jog"} or mode not in {"step", "jog"}
        ):
            raise ValueError(
                "Franka is moving home; use Stop before manual control"
                if self.mode == "home"
                else "Franka is stopping; release input and wait for the stop to finish"
            )
        if self.trajectory is None:
            self.trajectory = JointTrajectory(self.pose["joints"], goal, speed)
        else:
            if speed != self.speed:
                raise ValueError("Release input before changing Franka speed")
            self.trajectory.target(goal)
        self.mode, self.speed = mode, speed
        self.deadline = self.updated + 0.2

    def apply(self, request: dict):
        self.advance()
        method, params = request.get("method"), request.get("params") or {}
        if method in {"hold", "get_state"}:
            if method == "hold":
                self._stop()
                if "left" in self.pose:
                    self._grip_targets(self.grip.stop(self._grippers()))
                    for arm in self.pose:
                        measured = self.feedback.get("joints_deg", {}).get(arm, self.pose[arm])
                        self.pose[arm][4] = measured[4]
            return self._state()
        if method == "set_home" and "joints" in self.pose:
            if set(params) - {"speed_deg_s"}:
                raise ValueError("Home uses the configured pose")
            self._target(
                list(FRANKA_HOME), "home", speed_value(params.get("speed_deg_s"), FRANKA_SPEED)
            )
        elif method == "set_home" and "left" in self.pose:
            if params:
                raise ValueError("Home uses the configured pose")
            self._grip_targets(self.grip.stop(self._grippers()))
            for arm, pose in self.pose.items():
                pose[:4] = MIRA_HOME
                pose[4] = self.feedback.get("joints_deg", {}).get(arm, pose)[4]
        elif method == "jog_gripper" and "left" in self.pose:
            self.grip.command(gripper_rates(params, self.gripper_ranges), self._grippers())
        elif method == "set_joint_delta" and "joints" in self.pose:
            movement = values(params["joints"], 7, 5)
            limits = [
                (-166, 166),
                (-101, 101),
                (-166, 166),
                (-176, -4),
                (-166, 166),
                (-1, 215),
                (-166, 166),
            ]
            goal = [
                max(lo, min(hi, old + change))
                for old, change, (lo, hi) in zip(
                    self.trajectory.input.target_position
                    if params.get("step") and self.trajectory
                    else self.pose["joints"],
                    movement,
                    limits,
                    strict=True,
                )
            ]
            self._target(
                goal,
                "step" if params.get("step") else "jog",
                speed_value(params.get("speed_deg_s"), FRANKA_SPEED),
            )
        elif method == "set_mira_cartesian_delta" and "left" in self.pose:
            arms = {arm: values(params[arm], 5, 5) for arm in self.pose}
            rolls = {
                arm: roll_target(
                    self.feedback.get("joints_deg", {}).get(arm, self.pose[arm])[4], movement[4]
                )
                for arm, movement in arms.items()
            }
            for arm, movement in arms.items():
                signs = [1, 1, 1, 1] if arm == "left" else [1, -1, 1, -1]
                for index, (value, sign) in enumerate(zip(movement[:4], signs, strict=True)):
                    self.pose[arm][index] = max(
                        -180, min(180, self.pose[arm][index] + sign * value)
                    )
                if movement[4]:
                    self.pose[arm][4] = rolls[arm]
        else:
            raise ValueError(f"unsupported simulator method: {method}")

        return self._state()
