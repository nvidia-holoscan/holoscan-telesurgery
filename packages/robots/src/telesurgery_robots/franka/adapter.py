# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physical Franka feedback and bounded jogs through a local native FCI loop."""

import math

from telesurgery_robots.adapters.base import speed_value
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED


class Franka:
    simulation = False
    manages_connection = True
    groups = {"joints": 7}
    step_deg = 1.0
    max_step_deg = 5.0
    home_deg = {"joints": FRANKA_HOME}
    speed_limits = FRANKA_SPEED

    def __init__(self, spec):
        try:
            from telesurgery_robots.franka._franka import Controller
        except ImportError as exc:
            raise RuntimeError(
                f"Franka dependency unavailable ({exc}); run scripts/build_franka.sh on this node"
            ) from exc
        self.factory, self.address, self.reader = Controller, spec["address"], None

    def read(self):
        try:
            if self.reader is None:
                self.reader = self.factory(self.address)
            state = self.reader.read()
        except Exception:
            self.close()
            raise
        return {
            "joints_deg": {"joints": [math.degrees(v) for v in state["q"]]},
            "velocity_deg_s": {"joints": [math.degrees(v) for v in state["dq"]]},
            "effort_nm": {"joints": state["tau_J"]},
            "tool_pose": {
                "frame": "base",
                "matrix": state["O_T_EE"],
                "layout": "column-major",
                "unit": "m",
            },
            "mode": state["mode"],
            "faults": state["faults"],
            "device_time_ms": state["device_time_ms"],
            "feedback_source": "FCI measured state",
            "control_active": state["control_active"],
            "home_active": state["home_active"],
        }

    def jog(self, command, *, speed_deg_s=None):
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

    def close(self):
        if self.reader is not None:
            self.reader.close()
        self.reader = None
