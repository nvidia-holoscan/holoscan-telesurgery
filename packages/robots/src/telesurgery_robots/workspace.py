# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Model-derived Cartesian operating extents, calculated without robot motion.

An extent is travel along one base axis at the reference tool orientation. It
is not a collision-free box: corners and changed orientations still need the
robot's ordinary IK, joint limits and motion guards.
"""

import threading

import numpy as np


def skew(vector):
    x, y, z = vector
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])


class SerialModel:
    """Exact serial-chain FK from one measured pose and geometric Jacobian.

    Joint columns must be in base-to-tool chain order. Convert each column to
    a spatial screw at the reference configuration, then use the product of
    exponentials. This preserves the loaded asset's geometry and tool offset;
    it is not a constant-Jacobian approximation. Joint coordinates are radians
    for revolute joints and metres for prismatic joints.
    """

    def __init__(self, q, position, rotation, jacobian):
        self.q = np.asarray(q, dtype=float).copy()
        position, rotation = np.asarray(position), np.asarray(rotation)
        jacobian = np.asarray(jacobian, dtype=float)
        if (
            jacobian.shape != (6, len(self.q))
            or position.shape != (3,)
            or rotation.shape != (3, 3)
            or not all(np.isfinite(v).all() for v in (self.q, position, rotation, jacobian))
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3)
            or np.linalg.det(rotation) < 0.99
        ):
            raise ValueError("Invalid workspace kinematics")
        angular = np.linalg.norm(jacobian[3:], axis=0)
        if not np.all((angular < 1e-6) | (abs(angular - 1) < 1e-3)):
            raise ValueError("Workspace requires a serial-chain geometric Jacobian")
        self.home = np.eye(4)
        self.home[:3, :3], self.home[:3, 3] = rotation, position
        self.screws = jacobian.copy()
        self.screws[:3] += skew(position) @ jacobian[3:]

    def __call__(self, q):
        transform = np.eye(4)
        spatial = np.empty_like(self.screws)
        for index, delta in enumerate(np.asarray(q) - self.q):
            v, w = self.screws[:3, index], self.screws[3:, index]
            rotation, position = transform[:3, :3], transform[:3, 3]
            spatial[3:, index] = rotation @ w
            spatial[:3, index] = rotation @ v + np.cross(position, rotation @ w)
            step = np.eye(4)
            if np.linalg.norm(w) < 1e-6:
                step[:3, 3] = v * delta
            else:
                cross = skew(w)
                square = cross @ cross
                step[:3, :3] += np.sin(delta) * cross + (1 - np.cos(delta)) * square
                step[:3, 3] = (
                    np.eye(3) * delta
                    + (1 - np.cos(delta)) * cross
                    + (delta - np.sin(delta)) * square
                ) @ v
            transform = transform @ step
        pose = transform @ self.home
        spatial[:3] -= skew(pose[:3, 3]) @ spatial[3:]
        return pose, spatial


def axis_bounds(model, reference, limits, cancelled):
    """Trace six continuous IK paths on a model, holding reference orientation."""
    reference, limits = np.asarray(reference), np.asarray(limits)
    center, _ = model(reference)
    lower, upper = center[:3, 3].copy(), center[:3, 3].copy()
    # Leave more room than the native/simulated Cartesian controller's 0.02 rad reserve.
    lo, hi = limits[:, 0] + 0.035, limits[:, 1] - 0.035
    if np.any(reference < lo) or np.any(reference > hi):
        raise ValueError("Move away from the joint limit before starting Haply.")
    for axis in range(3):
        for sign in (-1, 1):
            q, target = reference.copy(), center[:3, 3].copy()
            step = 0.005
            for _ in range(500):
                if cancelled.is_set():
                    raise ValueError("Workspace calculation cancelled")
                goal = target.copy()
                goal[axis] += sign * step
                candidate = q.copy()
                reached = False
                for _ in range(12):
                    pose, jacobian = model(candidate)
                    difference = center[:3, :3] @ pose[:3, :3].T
                    angular = (
                        np.array(
                            [
                                difference[2, 1] - difference[1, 2],
                                difference[0, 2] - difference[2, 0],
                                difference[1, 0] - difference[0, 1],
                            ]
                        )
                        / 2
                    )
                    error = np.r_[goal - pose[:3, 3], angular]
                    if np.linalg.norm(error[:3]) < 0.0001 and np.linalg.norm(angular) < 0.001:
                        reached = True
                        break
                    delta = np.linalg.lstsq(jacobian, error, rcond=1e-3)[0]
                    if np.max(abs(delta)) > 0.08 or np.max(abs(candidate + delta - q)) > 0.12:
                        break  # Do not jump branches at a singularity.
                    candidate += delta
                    if np.any(candidate < lo) or np.any(candidate > hi):
                        break
                if not reached:
                    step /= 2
                    if step < 0.000625:
                        break
                    continue
                q, target = candidate, goal
                (lower if sign < 0 else upper)[axis] = target[axis]
    if np.any(upper - lower < 0.005):
        raise ValueError("Insufficient Cartesian travel here; reposition the arm before Start.")
    return {"min": lower.tolist(), "max": upper.tolist()}


class Workspace:
    """Nonblocking cache; no extent calculation runs in a robot control loop."""

    def __init__(self, frame="base"):
        self.frame = frame
        self.result = None
        self.reference = None
        self.error = "Calculating robot movement range."
        self.job = None
        self.cancelled = threading.Event()

    def update(self, position, orientation, calculate, *, idle):
        pose = np.r_[position, np.asarray(orientation).ravel()]
        outside = self.result is not None and (
            np.any(np.asarray(position) < np.asarray(self.result["min"]) - 0.002)
            or np.any(np.asarray(position) > np.asarray(self.result["max"]) + 0.002)
        )
        changed = self.reference is None or np.max(abs(pose - self.reference)) > 0.25
        if self.result is None and self.reference is not None:
            changed = np.max(abs(pose - self.reference)) > 0.01
        if (
            idle
            and (self.reference is None or outside or changed)
            and (self.job is None or not self.job.is_alive())
        ):
            self.reference = pose.copy()
            self.result = None
            self.error = "Calculating robot movement range."
            self.cancelled = threading.Event()
            cancelled = self.cancelled

            def run():
                try:
                    bounds = calculate(cancelled)
                    if not cancelled.is_set():
                        self.result = {"frame": self.frame, "unit": "m", **bounds}
                        self.error = ""
                except Exception as exc:
                    if not cancelled.is_set():
                        self.error = f"Robot movement range unavailable: {exc}"

            self.job = threading.Thread(target=run, name="robot-workspace", daemon=True)
            self.job.start()
        return self.result

    def close(self):
        self.cancelled.set()
        self.result = self.reference = None
