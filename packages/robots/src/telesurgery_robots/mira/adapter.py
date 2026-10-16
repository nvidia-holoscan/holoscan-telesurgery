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
    PHYSICAL_GRIP_SPEED,
    GripperJog,
    clamp,
    gripper_rates,
    opening_calibration,
    opening_position,
    vendor_positions,
)
from telesurgery_robots.mira.poses import (
    MIRA_HOME,
    MIRA_HOME_GRIP,
    MIRA_HOME_ROLL,
    MIRA_STEP_LIMIT,
    roll_target,
)
from telesurgery_robots.mira.velocity import PHYSICAL, JointVelocity
from telesurgery_robots.mira.workspace import vendor_bounds
from telesurgery_robots.workspace import Workspace


class Mira:
    """Bounded joint jogs based on measured position; never accumulate targets.

    Vendor motion messages are notifications. A following position query confirms
    communication, not completion of motion. Hold requests the measured position;
    the robot's physical emergency stop remains independent of this connection.
    """

    def __init__(self, uri, *, gripper_calibration=None):
        self.uri, self.client = uri, None
        self.gripper_calibration = opening_calibration(gripper_calibration)
        self.home_target = None
        self.home_holding = False
        self.home_deadline = 0.0
        self.home_settled = None
        self.home_sampled = 0.0
        self.grip = GripperJog()
        self.grip_stopping = set()
        self.roll_active = self.roll_holding = False
        self.tool_mode = False
        self.arm_holding = False
        self.jog_deadline = 0.0
        # Keep 50 ms of maximum-rate lead for both arm and roll axes.
        self.velocity = JointVelocity(PHYSICAL, roll_lead=CARTESIAN["roll_step_deg"])

    def state(self):
        if self.client is None:
            self.client = RpcClient(self.uri, broadcast=True)
            # The vendor broadcasts replies to every client on its local API.
            self.client.sequence = secrets.randbits(48)
        try:
            pose = self.client.send({"method": "get_mira_pose", "params": None})
            state = self._feedback(pose)
            rolling = self.velocity.roll
            target = self.velocity.advance(state["joints_deg"], time.monotonic())
            if target is not None:
                self.client.notify({"method": "set_mira_pose", "params": target})
                if rolling:
                    state = self._write_roll(target)
                state["control_active"] = self.velocity.active or bool(self.grip.rates)
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
            measured = vendor_positions(state["joints_deg"])
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
            near = all(
                all(
                    abs(joints[arm][index] - target) <= 1.0
                    for index, target in enumerate(targets[:5])
                )
                and abs(joints[arm][5] - targets[5]) <= GRIP_COUNTS[arm] * 0.01
                for arm, targets in self.home_target.items()
            )
            now = time.monotonic()
            if not near or now - self.home_sampled > 0.3:
                self.home_settled = None
            if near and (
                self.home_settled is None
                or any(
                    abs(value - self.home_settled[1][arm][index])
                    > (0.1 if index < 5 else GRIP_COUNTS[arm] * 0.01)
                    for arm in joints
                    for index, value in enumerate(joints[arm])
                )
            ):
                # The physical controller settles with a small position error.
                # Require a stable pose, not unattainable sub-degree accuracy.
                self.home_settled = now, {arm: row.copy() for arm, row in joints.items()}
            self.home_sampled = now
            if self.home_settled is not None and now - self.home_settled[0] >= 0.25:
                self.home_target = None
                self.home_settled = None
            elif now >= self.home_deadline:
                self._cancel_home()
                self.client.notify({"method": "set_mira_pose", "params": joints})
                raise RuntimeError("MIRA Home timed out after 30 seconds; hold requested")
        return {
            "joints_deg": joints,
            "grippers": {
                arm: opening_position(joints[arm][5], calibration)
                for arm, calibration in self.gripper_calibration.items()
            },
            "acknowledgement": "vendor cached position received",
            "hardware_timestamp_available": False,
            "stop_acknowledged": False,
            "control_active": self.home_target is not None
            or bool(self.grip.rates)
            or bool(self.jog_deadline)
            or self.velocity.active,
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
            "jog_joint_velocity",
        }:
            raise ValueError("Unsupported physical MIRA operation")
        if method == "set_home" and request.get("params"):
            raise ValueError("Home uses the configured pose")
        if method == "set_home" and self.home_target and self.state()["home_active"]:
            raise ValueError("MIRA is moving home; use Stop before manual control")
        movement = None
        if method == "jog_gripper":
            rates = gripper_rates(request.get("params"), GRIP_COUNTS, PHYSICAL_GRIP_SPEED)
        if method == "set_mira_joint_delta":
            movement = {
                arm: values(request["params"][arm], 5, MIRA_STEP_LIMIT) for arm in ("left", "right")
            }
        if method == "jog_mira_cartesian":
            movement = command(request.get("params"))
            self.tool_mode = True
        if method == "jog_joint_velocity":
            from telesurgery_robots.mira.velocity import command as velocity_command

            movement = velocity_command(request.get("params"), PHYSICAL)
        elif method != "jog_gripper":
            self.velocity.clear()
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
        if method == "jog_joint_velocity":
            self.jog_deadline = 0.0
            self.velocity.request(movement, pose, time.monotonic())
            state["control_active"] = True
            state["acknowledgement"] = "joint velocity accepted"
            return state
        if method == "jog_gripper":
            self.grip.command(rates, vendor_positions(pose))
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
            self.home_settled = None
            self.home_deadline = time.monotonic() + 30
        try:
            if method in {"jog_mira_cartesian", "set_mira_joint_delta"}:
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
        self.home_settled = None
        if self.home_target is not None:
            self.home_holding = True
            self.grip_stopping.update(self.home_target)
            self.home_target = None

    def close(self):
        self.arm_holding |= bool(self.jog_deadline) or self.velocity.active
        self.velocity.clear()
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
    grip_speed = PHYSICAL_GRIP_SPEED
    default_arm_speed_percent = 70
    default_roll_speed_percent = 90
    default_grip_speed_percent = 90
    joint_velocity = PHYSICAL
    control_period = 0.01

    @property
    def poll_interval(self):
        return self.control_period if self.client.velocity.active or self.client.grip.rates else 0.1

    def __init__(self, spec):
        self.client = Mira(spec["uri"], gripper_calibration=spec.get("gripper_calibration"))
        self.workspaces = {arm: Workspace(CARTESIAN["frame"]) for arm in self.groups}
        # A pose input device captures the measured tool pose before its first
        # move. Waiting for a Cartesian command would leave Start unable to arm.
        self.client.tool_mode = True

    def read(self):
        state = self.client.state()
        bounds, errors = {}, []
        for arm, workspace in self.workspaces.items():
            pose = state["cartesian_mm_deg"][arm]
            extent = workspace.update(
                [v / 1000 for v in pose[:3]],
                [math.radians(pose[3])],
                lambda cancelled, arm=arm: vendor_bounds(
                    self.client.uri, arm, state["cartesian_mm_deg"], state["joints_deg"], cancelled
                ),
                idle=not state["control_active"],
            )
            if extent:
                bounds[arm] = extent
            if workspace.error:
                errors.append(f"{arm.title()}: {workspace.error}")
        return {
            **state,
            "feedback_source": "vendor cached pose",
            "cartesian_workspace": bounds,
            "workspace_error": " · ".join(errors),
        }

    def jog(self, command):
        return self.client.send({"method": "set_mira_joint_delta", "params": command})

    def jog_velocity(self, command):
        return self.client.send({"method": "jog_joint_velocity", "params": command})

    def jog_cartesian(self, movement):
        return self.client.send({"method": "jog_mira_cartesian", "params": movement})

    def hold(self):
        return self.client.send({"method": "hold"})

    def home(self):
        return self.client.send({"method": "set_home"})

    def grip(self, command):
        return self.client.send({"method": "jog_gripper", "params": command})

    def close(self):
        for workspace in self.workspaces.values():
            workspace.close()
        self.client.close()
