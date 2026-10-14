# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Sim's local controller protocol behind the same physical adapter contract."""

from telesurgery_core.transport.rpc import RpcClient
from telesurgery_robots.adapters.base import cartesian_command, speed_value
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED
from telesurgery_robots.mira.cartesian import SIM_CARTESIAN
from telesurgery_robots.mira.gripper import GRIP_SPEED
from telesurgery_robots.mira.poses import MIRA_SIM_HOME
from telesurgery_robots.versius import HOME as VERSIUS_HOME


class SimulationAdapter:
    simulation = True
    step_deg = 1.0
    max_step_deg = 5.0

    def __init__(self, spec):
        self.uri, self.client = spec["uri"], None

    def request(self, method, params=None, *, timeout=0.5):
        if self.client is None:
            self.client = RpcClient(self.uri)
        try:
            self.client.timeout = timeout
            return self.client.send({"method": method, "params": params or {}})
        except Exception:
            self.close()
            raise

    def read(self):
        return self.request("get_state")

    def jog(self, command):
        return self.request(self.method, command)

    def hold(self):
        return self.request("hold")

    def reset(self):
        return self.request("reset_scene", timeout=1.5)

    def close(self):
        if self.client:
            self.client.close()
            self.client = None


class MiraSimulation(SimulationAdapter):
    mira_cartesian = SIM_CARTESIAN

    def jog_cartesian(self, command):
        return self.request("jog_mira_cartesian", command)

    groups = {"left": 5, "right": 5}
    method = "set_mira_cartesian_delta"
    home_deg = MIRA_SIM_HOME
    grippers = ("left", "right")
    grip_speed = GRIP_SPEED

    def home(self):
        return self.request("set_home")

    def grip(self, command):
        return self.request("jog_gripper", command)


class FrankaSimulation(SimulationAdapter):
    groups = {"joints": 7}
    method = "set_joint_delta"
    home_deg = {"joints": FRANKA_HOME}
    speed_limits = FRANKA_SPEED
    cartesian = {"frame": "base", "linear_speed_m_s": 0.10, "angular_speed_deg_s": 30.0}
    grippers = ()
    grip_speed = GRIP_SPEED

    def read(self):
        state = super().read()
        self.grippers = ("hand",) if state.get("gripper_available") else ()
        return state

    def jog(self, command, *, speed_deg_s=None):
        if "translation" in command or "rotation" in command:
            return self.request(
                "set_cartesian_velocity",
                {
                    **cartesian_command(command),
                    "speed_deg_s": speed_value(speed_deg_s, self.speed_limits),
                },
            )
        return self.request(
            self.method, {**command, "speed_deg_s": speed_value(speed_deg_s, self.speed_limits)}
        )

    def step(self, command, *, speed_deg_s=None):
        return self.request(
            self.method,
            {**command, "step": True, "speed_deg_s": speed_value(speed_deg_s, self.speed_limits)},
        )

    def home(self, *, speed_deg_s=None):
        return self.request(
            "set_home", {"speed_deg_s": speed_value(speed_deg_s, self.speed_limits)}
        )

    def grip(self, command):
        return self.request("jog_gripper", command)


class VersiusSimulation(FrankaSimulation):
    groups = {"joints": 8}
    home_deg = {"joints": VERSIUS_HOME}
    grippers = ("hand",)
