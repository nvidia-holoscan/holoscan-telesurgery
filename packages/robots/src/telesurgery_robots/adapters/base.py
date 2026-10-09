# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The adapter contract; hardware access runs only in the node's Holoscan graph."""

import math
from typing import Protocol


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
        **(
            {"grippers": adapter.grippers, "grip_speed_pct_s": adapter.grip_speed}
            if enabled and hasattr(adapter, "grip") and adapter.grippers
            else {}
        ),
        **({"speed_deg_s": adapter.speed_limits} if hasattr(adapter, "speed_limits") else {}),
        **({"cartesian": adapter.cartesian} if enabled and hasattr(adapter, "cartesian") else {}),
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
    if not isinstance(command, dict) or set(command) != {"translation", "rotation"}:
        raise ValueError("Cartesian input requires translation and rotation")
    return {key: values(command[key], 3, 1) for key in ("translation", "rotation")}
