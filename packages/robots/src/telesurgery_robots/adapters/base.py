# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The adapter contract; hardware access runs only in the node's Holoscan graph."""

import math
from typing import Protocol

CARTESIAN_SPEED = {
    "frame": "base",
    "linear_speed_m_s": 0.10,
    "angular_speed_deg_s": 30.0,
    "independent_rotation": True,
}


def values(data, length: int, bound: float) -> list[float]:
    if not isinstance(data, list) or len(data) != length:
        raise ValueError(f"expected {length} values")
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > bound for v in data):
        raise ValueError("invalid motion values")
    return [float(v) for v in data]


def speed_value(value, limits):
    if value is None:
        return limits["default"]
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not limits["min"] <= value <= limits["max"]
    ):
        raise ValueError(f"Speed must be between {limits['min']} and {limits['max']} °/s")
    return float(value)


class Adapter(Protocol):
    simulation: bool
    groups: dict[str, int]
    max_step_deg: float

    def __init__(self, spec: dict): ...
    def read(self) -> dict: ...
    def jog(self, command: dict) -> dict: ...
    def hold(self) -> dict: ...
    def close(self) -> None: ...


def controls(adapter: Adapter, spec: dict) -> dict:
    enabled = adapter.simulation or spec.get("motion_enabled") is True
    return {
        "read_only": not adapter.groups,
        "inputs": ["keyboard", "gamepad"] if enabled and adapter.groups else [],
        "groups": adapter.groups if enabled else {},
        "step_deg": min(0.4, adapter.max_step_deg),
        "default_step_deg": getattr(adapter, "step_deg", min(0.2, adapter.max_step_deg)),
        "max_step_deg": adapter.max_step_deg,
        **({"step_mode": True} if hasattr(adapter, "step") else {}),
        **({"home_deg": adapter.home_deg} if enabled and hasattr(adapter, "home") else {}),
        **({"reset_scene": True} if adapter.simulation and hasattr(adapter, "reset") else {}),
        **(
            {"grippers": adapter.grippers, "grip_speed_pct_s": adapter.grip_speed}
            if enabled and hasattr(adapter, "grip") and adapter.grippers
            else {}
        ),
        **({"speed_deg_s": adapter.speed_limits} if hasattr(adapter, "speed_limits") else {}),
        **{
            f"default_{kind}_speed_percent": getattr(adapter, f"default_{kind}_speed_percent")
            for kind in ("arm", "roll", "grip")
            if hasattr(adapter, f"default_{kind}_speed_percent")
        },
        **({"cartesian": adapter.cartesian} if enabled and hasattr(adapter, "cartesian") else {}),
        **(
            {"joint_velocity": adapter.joint_velocity}
            if enabled and hasattr(adapter, "joint_velocity")
            else {}
        ),
        **(
            {"mira_follow": adapter.mira_follow}
            if adapter.simulation and hasattr(adapter, "mira_follow")
            else {}
        ),
        **(
            {"mira_cartesian": adapter.mira_cartesian}
            if enabled and hasattr(adapter, "mira_cartesian")
            else {}
        ),
        "reason": "State feedback only; motion is not supported"
        if not adapter.groups
        else ""
        if enabled
        else "Physical motion awaits supervised validation",
    }


def validate_jog(adapter: Adapter, command: dict) -> dict:
    if not isinstance(command, dict) or command.keys() != adapter.groups.keys():
        raise ValueError("Command must contain the robot's joint groups")
    return {
        key: values(command[key], count, adapter.max_step_deg)
        for key, count in adapter.groups.items()
    }


def cartesian_command(command):
    """Dimensionless, base-frame velocity requests; limits live on the node."""
    if (
        not isinstance(command, dict)
        or not {"translation", "rotation"} <= set(command)
        or set(command) - {"translation", "rotation", "rotation_speed_deg_s"}
    ):
        raise ValueError("Cartesian input requires translation and rotation")
    result = {key: values(command[key], 3, 1) for key in ("translation", "rotation")}
    if "rotation_speed_deg_s" in command:
        result["rotation_speed_deg_s"] = speed_value(
            command["rotation_speed_deg_s"],
            {
                "min": 0.3,
                "max": CARTESIAN_SPEED["angular_speed_deg_s"],
                "default": 15.0,
            },
        )
    return result


def cartesian_rates(command, arm_speed, maximum_joint_speed):
    """Apply independent tool rates through the existing bounded joint planner.

    Older recordings omit the rotation limit and retain their original behavior.
    The selected joint envelope stays constant even when one input axis is idle.
    """
    command = cartesian_command(command)
    rotation = command.pop("rotation_speed_deg_s", None)
    if rotation is None:
        return command, arm_speed
    rotational_joint_speed = maximum_joint_speed * rotation / CARTESIAN_SPEED["angular_speed_deg_s"]
    speed = max(arm_speed, rotational_joint_speed)
    for key, selected in (("translation", arm_speed), ("rotation", rotational_joint_speed)):
        vector = command[key]
        factor = selected / speed / max(1, math.hypot(*vector))
        command[key] = [v * factor for v in vector]
    return command, speed
