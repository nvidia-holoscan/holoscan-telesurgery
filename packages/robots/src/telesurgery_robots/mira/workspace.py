# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physical MIRA extents from read-only vendor IK, never simulation geometry."""

import copy
import secrets

import numpy as np
from telesurgery_core.transport.rpc import RequestRejected, RpcClient
from telesurgery_robots.adapters.base import values
from telesurgery_robots.mira.cartesian import JOINT_LIMITS


def vendor_bounds(uri, arm, poses, joints, cancelled):
    targets = copy.deepcopy(poses)
    lower = np.asarray(poses[arm][:3], dtype=float)
    upper = lower.copy()
    limits = np.asarray(JOINT_LIMITS)
    client = RpcClient(uri, broadcast=True)
    client.sequence = secrets.randbits(48)
    try:
        for axis in range(3):
            for sign in (-1, 1):
                target = list(poses[arm])
                previous = np.asarray(joints[arm][:4])
                step = 2.0
                for _ in range(200):
                    if cancelled.is_set():
                        raise ValueError("Workspace calculation cancelled")
                    candidate = target.copy()
                    candidate[axis] += sign * step
                    targets[arm] = candidate
                    valid = False
                    try:
                        solution = client.send(
                            {"method": "get_mira_cartesian_ik", "params": targets}
                        )
                        q = np.asarray(values(solution[arm], 6, float("inf"))[:4])
                        valid = (
                            np.all(q >= limits[:, 0] + 1)
                            and np.all(q <= limits[:, 1] - 1)
                            and np.max(abs(q - previous)) <= 5
                        )
                    except RequestRejected:
                        pass  # A reachable boundary is not a transport failure.
                    if not valid:
                        step /= 2
                        if step < 0.25:
                            break
                        continue
                    target, previous = candidate, q
                    (lower if sign < 0 else upper)[axis] = candidate[axis]
        if np.any(upper - lower < 1):
            raise ValueError("Insufficient Cartesian travel here; reposition the arm before Start.")
        return {"min": (lower / 1000).tolist(), "max": (upper / 1000).tolist()}
    finally:
        client.close()
