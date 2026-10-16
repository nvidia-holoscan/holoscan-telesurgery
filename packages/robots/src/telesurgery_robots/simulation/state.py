# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Simulation drive targets: planned Franka motion and MIRA joint-space demonstration."""

from __future__ import annotations

import time

import numpy as np
from telesurgery_robots.adapters.base import cartesian_rates, speed_value, values
from telesurgery_robots.franka.cartesian import JOINT_LIMITS, CartesianTrajectory
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED
from telesurgery_robots.franka.trajectory import JointTrajectory
from telesurgery_robots.mira.cartesian import SIM_CARTESIAN
from telesurgery_robots.mira.cartesian import command as tool_command
from telesurgery_robots.mira.follow import Follow
from telesurgery_robots.mira.follow import command as follow_command
from telesurgery_robots.mira.gripper import GripperJog, clamp, gripper_rates
from telesurgery_robots.mira.poses import (
    MIRA_HOME_GRIP,
    MIRA_HOME_ROLL,
    MIRA_SIM_HOME,
    roll_target,
)
from telesurgery_robots.mira.velocity import SIMULATION, JointVelocity
from telesurgery_robots.mira.velocity import command as velocity_command


class SimRobot:
    # LJ6_1_joint and RJ6_joint limits in the MIRA USD; the jaws are mirrored.
    gripper_ranges = {"left": (0.0, 40.0), "right": (-0.1, -40.0)}

    def __init__(self, environment="mira"):
        self.pose = {
            arm: [*MIRA_SIM_HOME[arm], MIRA_HOME_ROLL, closed + MIRA_HOME_GRIP * (opened - closed)]
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
        self.grip = GripperJog(retain_closing_load=environment in {"mira", "versius"})
        self.mira_progress = {}
        self.mira_follow = None
        self.mira_follow_error = ""
        self.mira_velocity = JointVelocity(SIMULATION)

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
        if self.mode in {"mira-tool", "mira-follow", "mira-velocity"} and now >= self.deadline:
            self._stop()
        if self.mira_velocity.active:
            if self.kinematics is None or now - self.kinematics[1] > 0.3:
                self._stop()
            else:
                measured = {arm: data[0][:5].tolist() for arm, data in self.kinematics[0].items()}
                limits = {arm: data[3] for arm, data in self.kinematics[0].items()}
                targets = self.mira_velocity.advance(measured, now, limits)
                if targets:
                    for arm, row in targets.items():
                        self.pose[arm][:5] = row[:5]
                if not self.mira_velocity.active:
                    self.mode = None
        if self.mira_follow is not None:
            if self.kinematics is None or now - self.kinematics[1] > 0.3:
                self.mira_follow_error = "MIRA physics feedback is stale"
                self._stop()
            else:
                follower = self.mira_follow
                self.pose[follower.arm][:5] = follower.advance(
                    self.kinematics[0][follower.arm], elapsed, now
                ).tolist()
                if follower.error:
                    self.mira_follow_error = follower.error
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
        if self.mode in {"mira-tool", "mira-follow", "mira-velocity"}:
            for arm in self.pose:
                measured = self.feedback.get("joints_deg", {}).get(arm, self.pose[arm])
                self.pose[arm][:5] = measured[:5]
            self.mode = None
        self.mira_follow = None
        self.mira_velocity.clear()
        self.mira_progress.clear()
        self._grip_targets(self.grip.stop(self._grippers()))
        if self.cartesian:
            self.cartesian.stop()
        if self.trajectory:
            self.trajectory.stop()
            self.mode = "stopping"

    def _state(self):
        tool_targets = {}
        cartesian_age = (
            max(0.0, time.monotonic() - self.kinematics[2])
            if "joints" in self.pose and self.kinematics is not None
            else None
        )
        if "left" in self.pose and self.kinematics is not None:
            for arm, (measured, position, jacobian, _) in self.kinematics[0].items():
                # Linearize the nearby commanded pose using the same live
                # Jacobian as IK. Keep this distinct from measured feedback.
                delta = np.asarray(self.pose[arm][:4]) - measured[:4]
                tool_targets[arm] = (position + jacobian @ delta).tolist()
        return {
            "targets_deg": {arm: list(pose) for arm, pose in self.pose.items()},
            "acknowledgement": "controller target accepted",
            **self.feedback,
            **({"cartesian_target_mm_deg": tool_targets} if tool_targets else {}),
            **(
                {
                    "mira_follow": {
                        "limited": bool(self.mira_follow and self.mira_follow.limited),
                        "id": self.mira_follow.target["id"] if self.mira_follow else None,
                        "error": self.mira_follow_error,
                    }
                }
                if "left" in self.pose
                else {}
            ),
            **(
                {
                    # A successful RPC is not a new physics sample. Replay
                    # must see the same freshness bound used by Cartesian jogs.
                    "cartesian_feedback": {
                        "ready": cartesian_age is not None and cartesian_age <= 0.3,
                        "age_ms": cartesian_age * 1000 if cartesian_age is not None else None,
                    },
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
                    "control_active": self.mode
                    in {"home", "mira-tool", "mira-follow", "mira-velocity"}
                    or bool(self.grip.rates),
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
                was_home = self.mode == "home"
                self._stop()
                self.mira_follow_error = ""
                if "left" in self.pose:
                    self.grip.clear()
                    # Keep an existing grasp loaded. Replacing a closing
                    # target with the measured aperture removes its force.
                    measured_grip = self._grippers()
                    self._grip_targets(
                        {
                            arm: measured_grip[arm]
                            if was_home
                            else min(
                                measured_grip[arm],
                                (self.pose[arm][5] - closed) / (opened - closed),
                            )
                            for arm, (closed, opened) in self.gripper_ranges.items()
                        }
                    )
                    for arm in self.pose:
                        measured = self.feedback.get("joints_deg", {}).get(arm, self.pose[arm])
                        if self.mode == "home":
                            self.pose[arm][:4] = measured[:4]
                        self.pose[arm][4] = measured[4]
                    self.mode = None
            return self._state()
        if "left" in self.pose and self.mode == "home":
            raise ValueError("MIRA is moving home; use Stop before manual control")
        if self.mode == "mira-follow" and method != "set_mira_tool_target":
            raise ValueError("Release MIRA target following before changing input")
        if self.mode == "mira-velocity" and method not in {
            "set_mira_joint_velocity",
            "jog_gripper",
        }:
            raise ValueError("Release joint velocity input before changing input")
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
            for arm, pose in self.pose.items():
                pose[:4] = MIRA_SIM_HOME[arm]
                pose[4] = MIRA_HOME_ROLL
            self.mode = "home"
        elif method == "jog_gripper":
            if self.mode in {"home", "stopping"} or (self.cartesian and self.cartesian.stopping):
                raise ValueError("Franka is busy; release input before gripping")
            self.grip.command(gripper_rates(params, self.gripper_ranges), self._grippers())
        elif method == "set_cartesian_velocity" and "joints" in self.pose:
            command, speed = cartesian_rates(
                {key: value for key, value in params.items() if key != "speed_deg_s"},
                speed_value(params.get("speed_deg_s"), FRANKA_SPEED),
                FRANKA_SPEED["max"],
            )
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
        elif method == "set_mira_joint_velocity" and "left" in self.pose:
            rates = velocity_command(params, SIMULATION)
            if self.mode not in {None, "mira-velocity"}:
                raise ValueError("Release input before MIRA joint velocity control")
            if self.kinematics is None or time.monotonic() - self.kinematics[1] > 0.3:
                raise ValueError("MIRA physics feedback is unavailable or stale")
            measured = {arm: data[0][:5].tolist() for arm, data in self.kinematics[0].items()}
            # Match the existing mirrored right-arm keyboard/gamepad controls.
            rates["right"] = [
                v * sign for v, sign in zip(rates["right"], (1, -1, 1, -1, 1), strict=True)
            ]
            self.mira_velocity.request(rates, measured, time.monotonic())
            self.mode, self.deadline = "mira-velocity", time.monotonic() + 0.2
        elif method == "set_mira_tool_target" and "left" in self.pose:
            target = follow_command(params)
            if self.mira_follow_error:
                raise ValueError(self.mira_follow_error)
            if self.mode not in {None, "mira-follow"}:
                raise ValueError("Release input before MIRA target following")
            if self.kinematics is None or time.monotonic() - self.kinematics[1] > 0.3:
                raise ValueError("MIRA Cartesian physics feedback is unavailable or stale")
            arm = target["arm"]
            workspace = self.feedback.get("mira_workspace_mm", {}).get(arm)
            if workspace is None:
                raise ValueError("MIRA workspace calibration is unavailable")
            target["pose"][:3] = np.clip(
                target["pose"][:3], workspace["min"], workspace["max"]
            ).tolist()
            if self.mira_follow is None:
                for side, data in self.kinematics[0].items():
                    self.pose[side][:5] = data[0][:5].tolist()
                self.mira_follow = Follow(arm, self.kinematics[0][arm][0], time.monotonic())
            elif self.mira_follow.arm != arm:
                raise ValueError("Release input before switching MIRA arms")
            self.mira_follow.request(target)
            self.mode, self.deadline = "mira-follow", time.monotonic() + 0.2
        elif method == "jog_mira_cartesian" and "left" in self.pose:
            movement = tool_command(params, SIM_CARTESIAN)
            if self.kinematics is None or time.monotonic() - self.kinematics[1] > 0.3:
                raise ValueError("MIRA Cartesian physics feedback is unavailable or stale")
            targets = {arm: list(pose) for arm, pose in self.pose.items()}
            for arm, delta in movement.items():
                measured, _, jacobian, limits = self.kinematics[0][arm]
                if self.mode != "mira-tool":
                    targets[arm][:5] = measured[:5].tolist()
                previous = np.asarray(targets[arm][:4])
                lead = previous - measured[:4]
                pending = np.max(np.abs(lead)) > 0.05
                now = time.monotonic()
                last, advanced = self.mira_progress.get(arm, (measured[:4], now))
                if not pending or np.max(np.abs(measured[:4] - last)) > 0.01:
                    last, advanced = measured[:4].copy(), now
                self.mira_progress[arm] = last, advanced
                if pending and now - advanced > 0.75:
                    self._stop()
                    raise ValueError("MIRA tool tracking error; release input before retrying")
                if any(delta[:4]):
                    change = np.linalg.lstsq(jacobian, np.asarray(delta[:4]), rcond=1e-4)[0]
                    if np.max(np.abs(jacobian @ change - delta[:4])) > 0.01:
                        raise ValueError("MIRA tool direction is unavailable at this configuration")
                    # Preserve travel not yet completed by physics. Replacing
                    # this with measured + change every packet loses most of
                    # small, continuous input. Bound the lead so contact cannot
                    # accumulate an arbitrary deferred move.
                    tool_lead = jacobian @ lead
                    if (
                        np.max(np.abs(lead)) > 1.01
                        or np.linalg.norm(tool_lead[:3])
                        > 2 * SIM_CARTESIAN["linear_step_mm"] + 0.01
                        or abs(tool_lead[3]) > 1.01
                    ):
                        self._stop()
                        raise ValueError("MIRA tool tracking error; release input before retrying")
                    # Scale the whole tool increment together. Angular motion
                    # can require several joint degrees even for a small tool
                    # angle; wait for physics inside the existing 1-degree
                    # lead envelope instead of rejecting normal servo delay.
                    fraction = min(1.0, 1.0 / max(1.0, np.max(np.abs(change))))
                    for old, step, actual, (lo, hi) in zip(
                        previous, change, measured[:4], limits, strict=True
                    ):
                        if (step > 0 and min(old, actual) >= hi - 0.01) or (
                            step < 0 and max(old, actual) <= lo + 0.01
                        ):
                            self._stop()
                            raise ValueError("MIRA Cartesian target exceeds joint limits")
                        if step > 0:
                            fraction = min(fraction, (min(hi, actual + 1) - old) / step)
                        elif step < 0:
                            fraction = min(fraction, (max(lo, actual - 1) - old) / step)
                    tool_change = jacobian @ change
                    if tool_change[3] > 0:
                        fraction = min(fraction, (1 - tool_lead[3]) / tool_change[3])
                    elif tool_change[3] < 0:
                        fraction = min(fraction, (-1 - tool_lead[3]) / tool_change[3])
                    distance = np.linalg.norm(tool_change[:3])
                    if distance > 0:
                        # Positive root of ||lead + fraction * change|| <= radius.
                        along = np.dot(tool_lead[:3], tool_change[:3])
                        radius = 2 * SIM_CARTESIAN["linear_step_mm"]
                        margin = radius**2 - np.dot(tool_lead[:3], tool_lead[:3])
                        fraction = min(
                            fraction,
                            (-along + np.sqrt(max(0, along**2 + distance**2 * margin)))
                            / distance**2,
                        )
                    goal = previous + change * max(0, fraction)
                    targets[arm][:4] = goal.tolist()
                if delta[4]:
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
