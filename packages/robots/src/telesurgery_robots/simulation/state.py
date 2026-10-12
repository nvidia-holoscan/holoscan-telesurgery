# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Simulation drive targets: planned Franka motion and MIRA joint-space demonstration."""

from __future__ import annotations

import time

import numpy as np
from telesurgery_robots.adapters.base import cartesian_command, speed_value, values
from telesurgery_robots.franka.cartesian import JOINT_LIMITS, CartesianTrajectory
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED
from telesurgery_robots.franka.trajectory import JointTrajectory
from telesurgery_robots.mira.cartesian import command as tool_command
from telesurgery_robots.mira.gripper import GripperJog, clamp, gripper_rates
from telesurgery_robots.mira.poses import MIRA_HOME, MIRA_HOME_GRIP, MIRA_HOME_ROLL, roll_target


class SimRobot:
    # LJ6_1_joint and RJ6_joint limits in the MIRA USD; the jaws are mirrored.
    gripper_ranges = {"left": (0.3, 40.0), "right": (-0.1, -40.0)}

    def __init__(self, environment="mira"):
        self.pose = {
            arm: [*MIRA_HOME, MIRA_HOME_ROLL, closed + MIRA_HOME_GRIP * (opened - closed)]
            for arm, (closed, opened) in self.gripper_ranges.items()
        }
        self.home = FRANKA_HOME
        self.limits = JOINT_LIMITS
        if environment == "versius":
            from telesurgery_robots.versius import HOME, LIMITS

            self.home, self.limits = HOME, np.asarray(LIMITS)
        if environment in {"franka", "versius"}:
            self.pose = {"joints": list(self.home)}
            self.gripper_ranges = {"hand": (0.0, 0.04)}
        self.finger_target = 0.04
        self.cartesian = None
        self.kinematics = None
        self.trajectory = None
        self.mode = None
        self.speed = FRANKA_SPEED["default"]
        self.updated = time.monotonic()
        self.deadline = 0.0
        self.feedback = {}
        self.grip = GripperJog()

    @property
    def joint_target_velocity(self):
        trajectory = self.cartesian or self.trajectory
        return (
            list(trajectory.input.current_velocity)
            if trajectory
            else [0.0] * len(self.pose.get("joints", range(7)))
        )

    def _grippers(self):
        if "joints" in self.pose:
            if not self.gripper_ranges:
                return {}
            return {
                "hand": clamp(
                    self.feedback.get("grippers", {}).get("hand", self.finger_target / 0.04)
                )
            }
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
            if arm == "hand":
                self.finger_target = closed + position * (opened - closed)
            else:
                self.pose[arm][5] = closed + position * (opened - closed)

    def advance(self, now=None):
        now = time.monotonic() if now is None else now
        elapsed = max(0, min(now - self.updated, 0.1))
        self.updated = now
        self._grip_targets(self.grip.advance(self._grippers()))
        if (
            "left" in self.pose
            and self.mode == "home"
            and all(
                all(
                    abs(actual - target) <= 0.2
                    for actual, target in zip(
                        self.feedback.get("joints_deg", {}).get(arm, pose[:5]),
                        pose[:5],
                        strict=True,
                    )
                )
                and abs(self.feedback.get("grippers_deg", {}).get(arm, pose[5]) - pose[5]) <= 0.2
                for arm, pose in self.pose.items()
            )
        ):
            self.mode = None
        if self.mode == "mira-tool" and now >= self.deadline:
            self._stop()
        if self.cartesian is not None and elapsed > 0:
            position, jacobian, sampled = self.kinematics or (self.pose["joints"], None, -1)
            if now - sampled > 0.3:
                self.cartesian.stop("physics feedback stale")
            self.pose["joints"] = self.cartesian.advance(position, jacobian, elapsed, now)
            if self.cartesian.finished:
                if self.cartesian.stop_reason == "joint tracking error":
                    # Contact blocked the requested position. Hold measured
                    # joints so the next jog can retreat from the obstacle.
                    self.pose["joints"] = list(position)
                self.cartesian = None
        if now > self.deadline and self.mode in {"jog", "home"} and "joints" in self.pose:
            self._stop()
        if self.trajectory is not None and elapsed > 0:
            self.pose["joints"] = self.trajectory.advance(elapsed)
            if self.trajectory.finished:
                self.trajectory = None
                if self.mode != "home":
                    self.mode = None
        if (
            "joints" in self.pose
            and self.mode == "home"
            and self.trajectory is None
            and all(abs(position - 1.0) <= 0.01 for position in self._grippers().values())
        ):
            self.mode = None

    def _stop(self):
        if "joints" in self.pose and self.mode == "home":
            self._grip_targets(self._grippers())
            if self.trajectory is None:
                self.mode = None
        if self.mode == "mira-tool":
            for arm in self.pose:
                measured = self.feedback.get("joints_deg", {}).get(arm, self.pose[arm])
                self.pose[arm][:5] = measured[:5]
            self.mode = None
        self._grip_targets(self.grip.stop(self._grippers()))
        if self.cartesian:
            self.cartesian.stop()
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
                    "control_active": self.mode == "home"
                    or self.trajectory is not None
                    or self.cartesian is not None
                    or bool(self.grip.rates),
                    "home_active": self.mode == "home",
                    "stopping": self.mode == "stopping"
                    or bool(self.cartesian and self.cartesian.stopping),
                    "stop_reason": self.cartesian.stop_reason if self.cartesian else None,
                    "grippers": self._grippers(),
                    "gripper_available": "hand" in self.gripper_ranges,
                }
                if "joints" in self.pose
                else {
                    "grippers": self._grippers(),
                    "control_active": self.mode in {"home", "mira-tool"} or bool(self.grip.rates),
                    "home_active": self.mode == "home",
                }
            ),
        }

    def _target(self, goal, mode, speed):
        if self.cartesian is not None:
            raise ValueError("Release Cartesian input before joint motion or Home")
        if self.mode in {"home", "stopping"} or (
            self.trajectory is not None
            and (self.mode not in {"step", "jog"} or mode not in {"step", "jog"})
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
        self.deadline = self.updated + (self.trajectory.duration + 30 if mode == "home" else 0.2)

    def apply(self, request: dict):
        self.advance()
        method, params = request.get("method"), request.get("params") or {}
        if method in {"hold", "get_state"}:
            if method == "hold":
                self._stop()
                if "left" in self.pose:
                    self.grip.clear()
                    self._grip_targets(self._grippers())
                    for arm in self.pose:
                        measured = self.feedback.get("joints_deg", {}).get(arm, self.pose[arm])
                        if self.mode == "home":
                            self.pose[arm][:4] = measured[:4]
                        self.pose[arm][4] = measured[4]
                    self.mode = None
            return self._state()
        if "left" in self.pose and self.mode == "home":
            raise ValueError("MIRA is moving home; use Stop before manual control")
        if method == "set_home" and "joints" in self.pose:
            if set(params) - {"speed_deg_s"}:
                raise ValueError("Home uses the configured pose")
            self._target(
                list(self.home), "home", speed_value(params.get("speed_deg_s"), FRANKA_SPEED)
            )
            self.grip.clear()
            self._grip_targets({arm: 1.0 for arm in self.gripper_ranges})
        elif method == "set_home" and "left" in self.pose:
            if params:
                raise ValueError("Home uses the configured pose")
            self.grip.clear()
            self._grip_targets({arm: MIRA_HOME_GRIP for arm in self.pose})
            for pose in self.pose.values():
                pose[:4] = MIRA_HOME
                pose[4] = MIRA_HOME_ROLL
            self.mode = "home"
        elif method == "jog_gripper":
            if self.mode in {"home", "stopping"} or (self.cartesian and self.cartesian.stopping):
                raise ValueError("Franka is busy; release input before gripping")
            self.grip.command(gripper_rates(params, self.gripper_ranges), self._grippers())
        elif method == "set_cartesian_velocity" and "joints" in self.pose:
            command = cartesian_command({key: params[key] for key in ("translation", "rotation")})
            if set(params) - {"translation", "rotation", "speed_deg_s"}:
                raise ValueError("Unexpected Cartesian parameters")
            speed = speed_value(params.get("speed_deg_s"), FRANKA_SPEED)
            if self.kinematics is None or time.monotonic() - self.kinematics[2] > 0.3:
                raise ValueError("Cartesian physics feedback is unavailable or stale")
            if self.trajectory is not None or self.mode == "home":
                raise ValueError("Release joint input or Home before Cartesian motion")
            if self.cartesian is not None and self.cartesian.stopping:
                # A command already in transit may arrive after the watchdog
                # or a release. Report the stop without treating it as a broken
                # controller connection; never refresh or resume that motion.
                return self._state()
            if self.cartesian is None:
                # Preserve the held drive target: re-seeding from measured
                # joints would accumulate load-induced position error on
                # every enable/release cycle. IK still uses measured joints.
                self.cartesian = CartesianTrajectory(self.pose["joints"], speed, self.limits)
            elif self.cartesian.speed != speed:
                raise ValueError("Release input before changing Franka speed")
            self.cartesian.request(command, self.updated)
        elif method == "set_joint_delta" and "joints" in self.pose:
            movement = values(params["joints"], len(self.home), 5)
            limits = self.limits
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
        elif method == "jog_mira_cartesian" and "left" in self.pose:
            movement = tool_command(params)
            if self.kinematics is None or time.monotonic() - self.kinematics[1] > 0.3:
                raise ValueError("MIRA Cartesian physics feedback is unavailable or stale")
            targets = {arm: list(pose) for arm, pose in self.pose.items()}
            for arm, delta in movement.items():
                measured, _, jacobian, limits = self.kinematics[0][arm]
                if any(delta[:4]):
                    change = np.linalg.lstsq(jacobian, np.asarray(delta[:4]), rcond=1e-4)[0]
                    if np.max(np.abs(jacobian @ change - delta[:4])) > 0.01:
                        raise ValueError("MIRA tool direction is unavailable at this configuration")
                    goal = measured[:4] + change
                    if np.max(np.abs(change)) > 1 or any(
                        not lo <= v <= hi for v, (lo, hi) in zip(goal, limits, strict=True)
                    ):
                        raise ValueError(
                            "MIRA Cartesian target exceeds joint limits; reduce arm speed"
                        )
                    targets[arm][:4] = goal.tolist()
                targets[arm][4] = roll_target(measured[4], delta[4])
            self.pose = targets
            self.mode, self.deadline = "mira-tool", time.monotonic() + 0.2
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
