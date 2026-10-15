# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA simulation commands and the physical vendor API."""

from __future__ import annotations

import math
import secrets
import time

from telesurgery_core.transport.rpc import RpcClient
from telesurgery_robots.adapters.base import values
from telesurgery_robots.mira.cartesian import CARTESIAN, bounded_solution, command, positions
from telesurgery_robots.mira.controller import MiraController
from telesurgery_robots.mira.gripper import (
    GRIP_COUNTS,
    GRIP_SPEED,
    GripperJog,
    clamp,
    gripper_rates,
)
from telesurgery_robots.mira.poses import (
    MIRA_HOME,
    MIRA_HOME_GRIP,
    MIRA_HOME_ROLL,
    MIRA_STEP_LIMIT,
    roll_target,
)


class Mira:
    """Bounded joint jogs based on measured position; never accumulate targets.

    Vendor motion messages are notifications. A following position query confirms
    communication, not completion of motion. Hold requests the measured position;
    the robot's physical emergency stop remains independent of this connection.
    """

    def __init__(self, uri):
        self.uri, self.client = uri, None
        self.home_target = None
        self.home_holding = False
        self.home_deadline = 0.0
        self.grip = GripperJog()
        self.grip_stopping = set()
        self.roll_active = self.roll_holding = False
        self.tool_mode = False
        self.arm_holding = False
        self.jog_deadline = 0.0

    def state(self):
        if self.client is None:
            self.client = RpcClient(self.uri, broadcast=True)
            # The vendor broadcasts replies to every client on its local API.
            self.client.sequence = secrets.randbits(48)
        try:
            pose = self.client.send({"method": "get_mira_pose", "params": None})
            state = self._feedback(pose)
            if self.arm_holding or self.jog_deadline and time.monotonic() >= self.jog_deadline:
                self.client.notify({"method": "set_mira_pose", "params": state["joints_deg"]})
                self.arm_holding = False
                self.jog_deadline = 0.0
                state["control_active"] = self.home_target is not None or bool(self.grip.rates)
            if self.home_holding:
                self.client.notify({"method": "set_mira_pose", "params": state["joints_deg"]})
                self.home_holding = False
            if self.roll_holding:
                state = self._write_roll(state["joints_deg"])
                self.roll_active = self.roll_holding = False
            measured = state["grippers"]
            targets = {arm: measured[arm] for arm in self.grip_stopping}
            targets.update(self.grip.advance(measured))
            if targets:
                state = self._write_grips(targets)
            if self.tool_mode:
                state["cartesian_mm_deg"] = positions(
                    self.client.send({"method": "get_mira_fkine_cartesian", "params": None})
                )
            return state
        except Exception:
            self.close()
            raise

    def _write_roll(self, joints):
        # The supplied binary supports absolute roll; deltas accumulate against
        # an unseen vendor target and cannot reliably stop at measured position.
        self.roll_active = True
        try:
            pose = self.client.command(
                {"method": "set_mira_roll", "params": {arm: joints[arm][4] for arm in GRIP_COUNTS}},
                {"method": "get_mira_pose", "params": None},
            )
            return self._feedback(pose)
        except Exception:
            self.roll_holding = True
            self.close()
            raise

    def _write_grips(self, targets):
        # Vendor gripper overrides persist independently of set_mira_pose.
        # On failure, retry only a measured-position hold, never the old target.
        self.grip_stopping.update(targets)
        try:
            for arm, target in targets.items():
                pose = self.client.command(
                    {"method": f"set_{arm}_gripper", "params": clamp(target)},
                    {"method": "get_mira_pose", "params": None},
                )
                state = self._feedback(pose)
                self.grip_stopping.discard(arm)
            return state
        except Exception:
            self.grip_stopping.update(self.grip.rates)
            self.grip.clear()
            raise

    def _feedback(self, pose):
        if not isinstance(pose, dict) or any(pose.get(arm) is None for arm in ("left", "right")):
            raise RuntimeError("MIRA is not reporting joint positions")
        # The vendor's sixth field is a tool-drive count, not an arm angle.
        joints = {
            # Feedback may overshoot the nominal command range slightly.
            arm: values(pose[arm][:5], 5, 360) + values(pose[arm][5:], 1, math.inf)
            for arm in ("left", "right")
        }
        if self.home_target:
            if all(
                all(
                    abs(joints[arm][index] - target) <= 0.2
                    for index, target in enumerate(targets[:5])
                )
                and abs(joints[arm][5] - targets[5]) <= GRIP_COUNTS[arm] * 0.01
                for arm, targets in self.home_target.items()
            ):
                self.home_target = None
            elif time.monotonic() >= self.home_deadline:
                self._cancel_home()
                self.client.notify({"method": "set_mira_pose", "params": joints})
                raise RuntimeError("MIRA Home timed out after 30 seconds; hold requested")
        return {
            "joints_deg": joints,
            "grippers": {
                arm: clamp(joints[arm][5] / maximum) for arm, maximum in GRIP_COUNTS.items()
            },
            "acknowledgement": "vendor cached position received",
            "hardware_timestamp_available": False,
            "stop_acknowledged": False,
            "control_active": self.home_target is not None
            or bool(self.grip.rates)
            or bool(self.jog_deadline),
            "home_active": self.home_target is not None,
            **({"targets_deg": self.home_target} if self.home_target else {}),
        }

    def send(self, request):
        method = request["method"]
        if method == "get_state":
            return self.state()
        if method not in {
            "hold",
            "set_home",
            "jog_gripper",
            "set_mira_joint_delta",
            "jog_mira_cartesian",
        }:
            raise ValueError("Unsupported physical MIRA operation")
        if method == "set_home" and request.get("params"):
            raise ValueError("Home uses the configured pose")
        if method == "set_home" and self.home_target and self.state()["home_active"]:
            raise ValueError("MIRA is moving home; use Stop before manual control")
        movement = None
        if method == "jog_gripper":
            rates = gripper_rates(request.get("params"), GRIP_COUNTS)
        if method == "set_mira_joint_delta":
            movement = {
                arm: values(request["params"][arm], 5, MIRA_STEP_LIMIT) for arm in ("left", "right")
            }
        if method == "jog_mira_cartesian":
            movement = command(request.get("params"))
            self.tool_mode = True
        if method in {"hold", "set_home"}:
            self.jog_deadline = 0.0
            if method == "hold":
                self._cancel_home()
            self.grip_stopping.update(self.grip.rates)
            self.grip.clear()
            self.roll_holding = self.roll_active
        state = self.state()
        pose = state["joints_deg"]
        if self.home_target and method != "hold":
            raise ValueError("MIRA is moving home; use Stop before manual control")
        if method == "jog_gripper":
            self.grip.command(rates, state["grippers"])
            state["control_active"] = True
            state["acknowledgement"] = "gripper input accepted"
            return state
        if method == "jog_mira_cartesian" and any(any(v[:4]) for v in movement.values()):
            # The vendor delta RPC adds to its persistent commanded target. Use
            # cached measured FK and query IK first instead; its motion RPC has
            # no success acknowledgement and can silently clamp unreachable XYZ.
            target = {
                arm: [
                    p + d
                    for p, d in zip(state["cartesian_mm_deg"][arm], movement[arm][:4], strict=True)
                ]
                for arm in pose
            }
            try:
                solution = self.client.send({"method": "get_mira_cartesian_ik", "params": target})
            except Exception:
                self.close()
                raise
            pose = bounded_solution(solution, pose, movement)
        if movement:
            # Validate both roll targets before sending either arm's command.
            rolls = {arm: roll_target(pose[arm][4], movement[arm][4]) for arm in pose}
            for arm in pose:
                if method == "set_mira_joint_delta":
                    for index, change in enumerate(movement[arm][:4]):
                        pose[arm][index] += change
                pose[arm][4] = rolls[arm]
        elif method == "set_home":
            for arm in pose:
                pose[arm] = [*MIRA_HOME, MIRA_HOME_ROLL, MIRA_HOME_GRIP * GRIP_COUNTS[arm]]
            self.home_target = pose
            self.home_deadline = time.monotonic() + 30
        try:
            if method == "jog_mira_cartesian":
                self.jog_deadline = time.monotonic() + 0.2
            self.client.notify({"method": "set_mira_pose", "params": pose})
            if method == "set_home" or movement and any(movement[arm][4] for arm in movement):
                self._write_roll(pose)
            if method == "set_home":
                self._write_grips({arm: MIRA_HOME_GRIP for arm in pose})
        except Exception:
            self.close()
            raise
        if method == "hold":
            self.home_target = None
        state = self.state()
        state["acknowledgement"] = {
            "hold": "hold target sent",
            "set_home": "home target sent",
            "set_mira_joint_delta": "jog target sent",
            "jog_mira_cartesian": "Cartesian target sent",
        }[method]
        return state

    def _cancel_home(self):
        if self.home_target is not None:
            self.home_holding = True
            self.grip_stopping.update(self.home_target)
            self.home_target = None

    def close(self):
        self.arm_holding |= bool(self.jog_deadline)
        self.jog_deadline = 0.0
        self._cancel_home()
        self.roll_holding = self.roll_active
        self.grip_stopping.update(self.grip.rates)
        self.grip.clear()
        if self.client:
            self.client.close()
            self.client = None


class MiraAdapter:
    mira_cartesian = CARTESIAN
    controller = MiraController
    simulation = False
    manages_connection = True
    groups = {"left": 5, "right": 5}
    step_deg = 1.0
    max_step_deg = MIRA_STEP_LIMIT
    home_deg = {"left": MIRA_HOME, "right": MIRA_HOME}
    grippers = ("left", "right")
    grip_speed = GRIP_SPEED

    def __init__(self, spec):
        self.client = Mira(spec["uri"])
        # A pose input device captures the measured tool pose before its first
        # move. Waiting for a Cartesian command would leave Start unable to arm.
        self.client.tool_mode = True

    def read(self):
        return {**self.client.state(), "feedback_source": "vendor cached pose"}

    def jog(self, command):
        return self.client.send({"method": "set_mira_joint_delta", "params": command})

    def jog_cartesian(self, movement):
        return self.client.send({"method": "jog_mira_cartesian", "params": movement})

    def hold(self):
        return self.client.send({"method": "hold"})

    def home(self):
        return self.client.send({"method": "set_home"})

    def grip(self, command):
        return self.client.send({"method": "jog_gripper", "params": command})

    def close(self):
        self.client.close()
