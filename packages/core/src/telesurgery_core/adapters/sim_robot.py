# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA joint-space demonstrator state. This is not the vendor's Cartesian IK."""

from __future__ import annotations

import math


def values(data, length: int, bound: float) -> list[float]:
    if not isinstance(data, list) or len(data) != length:
        raise ValueError(f"expected {length} values")
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > bound for v in data):
        raise ValueError("invalid motion values")
    return [float(v) for v in data]


class SimRobot:
    def __init__(self, environment="mira"):
        self.pose = {
            "left": [15.7, 80.6, 45.0, 98.9, 0.0, 0.0],
            "right": [15.7, 80.6, 45.0, 98.9, 0.0, 0.0],
        }
        if environment == "franka":
            self.pose = {"joints": [0.0, -45.0, 0.0, -135.0, 0.0, 90.0, 45.0]}

    def apply(self, request: dict):
        method, params = request.get("method"), request.get("params")
        if method in {"hold", "get_state"}:
            return {"targets_deg": self.pose, "acknowledgement": "drive targets assigned"}
        if method == "set_joint_delta" and "joints" in self.pose:
            movement = values(params["joints"], 7, 5)
            limits = [
                (-166, 166),
                (-101, 101),
                (-166, 166),
                (-176, -4),
                (-166, 166),
                (-1, 215),
                (-166, 166),
            ]
            self.pose["joints"] = [
                max(lo, min(hi, old + change))
                for old, change, (lo, hi) in zip(self.pose["joints"], movement, limits, strict=True)
            ]
        elif method == "set_mira_cartesian_delta" and "left" in self.pose:
            arms = {arm: values(params[arm], 4, 5) for arm in self.pose}
            for arm, movement in arms.items():
                signs = [1, 1, 1, 1] if arm == "left" else [1, -1, 1, -1]
                for index, (value, sign) in enumerate(zip(movement, signs, strict=True)):
                    self.pose[arm][index] = max(
                        -180, min(180, self.pose[arm][index] + sign * value)
                    )
        else:
            raise ValueError(f"unsupported simulator method: {method}")

        return {"targets_deg": self.pose, "acknowledgement": "drive targets assigned"}
