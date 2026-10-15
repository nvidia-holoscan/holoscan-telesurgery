# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA tool jog contract: millimetres and degrees in the vendor base frame."""

import math

from telesurgery_robots.adapters.base import values

ARMS = ("left", "right")
CARTESIAN = {
    "frame": "MIRA base",
    "axes": ["X", "Y", "Z", "Elbow", "Roll"],
    "linear_step_mm": 0.5,
    "angular_step_deg": 1.0,
}
SIM_CARTESIAN = {
    **CARTESIAN,
    "frame": "MIRA simulation base",
    "linear_step_mm": 5.0,
    "roll_step_deg": 5.0,
    # Inverse3 right / forward / up into the simulation's base frame.
    # The procedure camera looks along world +X; world +Y is up.
    "haply_basis": [[-1, 0, 0], [0, 0, 1], [0, 1, 0]],
}
JOINT_LIMITS = ((-70, 70), (5, 115), (-90, 225), (3, 150))


def command(data, limits=CARTESIAN):
    if not isinstance(data, dict) or set(data) != set(ARMS):
        raise ValueError("MIRA tool input requires both arms")
    result = {}
    for arm in ARMS:
        delta = values(data[arm], 5, math.inf)
        if math.hypot(*delta[:3]) > limits["linear_step_mm"] + 1e-9:
            raise ValueError(f"MIRA translation exceeds {limits['linear_step_mm']} mm per command")
        if abs(delta[3]) > limits["angular_step_deg"] or abs(delta[4]) > limits.get(
            "roll_step_deg", limits["angular_step_deg"]
        ):
            raise ValueError("MIRA rotation exceeds the angular step limit")
        result[arm] = delta
    return result


def positions(data):
    if not isinstance(data, dict) or set(data) != set(ARMS):
        raise ValueError("MIRA Cartesian feedback requires both arms")
    return {arm: values(data[arm], 4, 360) for arm in ARMS}


def bounded_solution(solution, measured, movement):
    """Reject an IK branch jump before sending either arm; preserve idle joints."""
    if not isinstance(solution, dict) or set(solution) != set(ARMS):
        raise ValueError("Invalid MIRA inverse kinematics result")
    target = {arm: list(measured[arm]) for arm in ARMS}
    for arm in ARMS:
        joints = values(solution[arm], 6, math.inf)
        if not any(movement[arm][:4]):
            continue
        for index, (lo, hi) in enumerate(JOINT_LIMITS):
            if not lo <= joints[index] <= hi:
                raise ValueError("MIRA Cartesian target exceeds joint limits")
            if abs(joints[index] - measured[arm][index]) > 1.0:
                raise ValueError("MIRA IK exceeds the 1° joint-step limit; reduce arm speed")
        target[arm][:4] = joints[:4]
    return target
