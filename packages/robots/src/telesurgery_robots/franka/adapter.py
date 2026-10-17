# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physical Franka feedback and bounded jogs through a local native FCI loop."""

import math

from telesurgery_robots.adapters.base import CARTESIAN_SPEED, cartesian_rates, speed_value, values
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED
from telesurgery_robots.workspace import Workspace, axis_bounds


class Franka:
    simulation = False
    manages_connection = True
    groups = {"joints": 7}
    step_deg = 1.0
    max_step_deg = 5.0
    home_deg = {"joints": FRANKA_HOME}
    speed_limits = FRANKA_SPEED
    default_arm_speed_percent = 75
    cartesian = CARTESIAN_SPEED

    def __init__(self, spec):
        try:
            from telesurgery_robots.franka._franka import Controller
        except ImportError as exc:
            raise RuntimeError(
                f"Franka dependency unavailable ({exc}); "
                "run ./setup.sh --profile franka on this node"
            ) from exc
        if not hasattr(Controller, "kinematics") or not hasattr(Controller, "request_stop"):
            raise RuntimeError(
                "Rebuild the Franka adapter: run ./scripts/build_franka.sh on this node"
            )
        self.factory, self.address, self.reader = Controller, spec["address"], None
        self.workspace = Workspace()
        self.tool_frames = None

    def movement_range(self, state):
        import numpy as np
        from telesurgery_robots.franka.cartesian import JOINT_LIMITS

        frames = (state["F_T_EE"], state["EE_T_K"])
        if frames != self.tool_frames:
            self.workspace.close()
            self.workspace = Workspace()
            self.tool_frames = frames
        # Capture a model and immutable tool frames, never the live read/command API.
        kinematics = self.reader.kinematics

        def model(q):
            pose, jacobian = kinematics(q.tolist(), *frames)
            return np.asarray(pose).reshape(4, 4, order="F"), np.asarray(jacobian).reshape(
                6, 7, order="F"
            )

        q = np.asarray(state["q"])
        transform = np.asarray(state["O_T_EE"]).reshape(4, 4, order="F")
        bounds = self.workspace.update(
            transform[:3, 3],
            transform[:3, :3],
            lambda cancelled: axis_bounds(model, q, np.deg2rad(JOINT_LIMITS), cancelled),
            idle=not state["control_active"] and state["mode"] == "idle",
        )
        return {
            "cartesian_workspace": {"hand": bounds} if bounds else {},
            "workspace_error": self.workspace.error,
        }

    def read(self):
        try:
            if self.reader is None:
                self.reader = self.factory(self.address)
            state = self.reader.read()
        except Exception:
            self.close()
            raise
        transform = values(state["O_T_EE"], 16, math.inf)
        return {
            **self.movement_range(state),
            "joints_deg": {"joints": [math.degrees(v) for v in state["q"]]},
            "velocity_deg_s": {"joints": [math.degrees(v) for v in state["dq"]]},
            "effort_nm": {"joints": state["tau_J"]},
            "tool_pose": {
                "frame": "base",
                "matrix": state["O_T_EE"],
                "layout": "column-major",
                "unit": "m",
                "position_m": transform[12:15],
                "orientation_matrix": [[transform[4 * j + i] for j in range(3)] for i in range(3)],
            },
            "mode": state["mode"],
            "faults": state["faults"],
            "device_time_ms": state["device_time_ms"],
            "feedback_source": "FCI measured state",
            "control_active": state["control_active"],
            "home_active": state["home_active"],
            "stopping": state["stopping"],
        }

    def jog(self, command, *, speed_deg_s=None):
        if isinstance(command, dict) and set(command) & {"translation", "rotation"}:
            command, speed = cartesian_rates(
                command, speed_value(speed_deg_s, self.speed_limits), self.speed_limits["max"]
            )
            speed = math.radians(speed)
            self.read()
            self.reader.jog_cartesian(command["translation"] + command["rotation"], speed=speed)
            return self.read()
        return self._move(command, step=False, speed_deg_s=speed_deg_s)

    def step(self, command, *, speed_deg_s=None):
        return self._move(command, step=True, speed_deg_s=speed_deg_s)

    def home(self, *, speed_deg_s=None):
        speed = math.radians(speed_value(speed_deg_s, self.speed_limits))
        self.read()
        self.reader.home([math.radians(v) for v in FRANKA_HOME], speed=speed)
        return self.read()

    def _move(self, command, *, step, speed_deg_s):
        from telesurgery_robots.adapters.base import values

        delta = values(command["joints"], 7, self.max_step_deg)
        speed = math.radians(speed_value(speed_deg_s, self.speed_limits))
        self.read()
        self.reader.jog([math.radians(v) for v in delta], step=step, speed=speed)
        return self.read()

    def hold(self):
        if self.reader is not None:
            self.reader.hold()
        return self.read()

    def request_stop(self):
        # The native method only sets atomics; it neither waits nor performs FCI I/O.
        reader = self.reader
        if reader is not None:
            reader.request_stop()

    def close(self):
        if hasattr(self, "workspace"):
            self.workspace.close()
            self.workspace = Workspace()
            self.tool_frames = None
        if self.reader is not None:
            self.reader.close()
        self.reader = None
