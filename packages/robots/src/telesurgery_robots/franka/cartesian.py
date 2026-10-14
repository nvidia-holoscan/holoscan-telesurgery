# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Damped differential IK using measured Isaac/PhysX Jacobians, in base axes.

The simulator uses this planner; physical Franka uses the native FCI loop.
This is not a collision planner.
No joint model is guessed: the scene supplies the measured 6x7 tool Jacobian.
"""

import numpy as np
from ruckig import (
    ControlInterface,
    InputParameter,
    OutputParameter,
    Result,
    Ruckig,
    Synchronization,
)

JOINT_LIMITS = np.array(
    [
        (-166, 166),
        (-101, 101),
        (-166, 166),
        (-176, -4),
        (-166, 166),
        (-1, 215),
        (-166, 166),
    ],
    dtype=float,
)


def joint_velocity(jacobian, position, translation, rotation, speed, limits=JOINT_LIMITS):
    jacobian = np.asarray(jacobian, dtype=float)
    position = np.asarray(position, dtype=float)
    if jacobian.shape != (6, len(limits)) or position.shape != (len(limits),):
        raise ValueError("Invalid Cartesian physics feedback")
    if not np.all(np.isfinite(jacobian)) or not np.all(np.isfinite(position)):
        raise ValueError("Nonfinite Cartesian physics feedback")
    scale = speed / 20.0
    linear, angular = np.array(translation, dtype=float), np.array(rotation, dtype=float)
    linear /= max(1, np.linalg.norm(linear))
    angular /= max(1, np.linalg.norm(angular))
    twist = np.r_[linear * 0.10 * scale, angular * np.deg2rad(30) * scale]
    # Damping bounds the solution near singularities; uniformly scale the
    # solution to preserve its direction when a joint reaches its speed limit.
    velocity = np.rad2deg(
        jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + 0.03**2 * np.eye(6), twist)
    )
    scale = min(1, speed / max(1e-9, np.max(np.abs(velocity))))
    velocity *= scale
    # Reserve braking room per joint. Stopping the whole arm when one joint
    # reaches its limit wastes the remaining joints of a redundant arm.
    reserve, taper = np.rad2deg([0.02, 0.15])
    limits = np.asarray(limits)
    lower = -speed * np.clip((position - limits[:, 0] - reserve) / taper, 0, 1)
    upper = speed * np.clip((limits[:, 1] - position - reserve) / taper, 0, 1)
    if np.all(velocity >= lower) and np.all(velocity <= upper):
        return velocity.tolist()
    return np.rad2deg(
        bounded_velocity(jacobian, twist * scale, np.deg2rad(lower), np.deg2rad(upper))
    ).tolist()


def bounded_velocity(jacobian, twist, lower, upper):
    """Solve the small damped least-squares problem with joint velocity bounds."""
    count = len(lower)
    hessian = jacobian.T @ jacobian + 0.03**2 * np.eye(count)
    rhs = jacobian.T @ twist
    velocity = np.zeros(count)  # Always a feasible initial point.
    active = np.zeros(count, dtype=int)
    for _ in range(4 * count * count):
        gradient = hessian @ velocity - rhs
        free = active == 0
        direction = np.zeros(count)
        if free.any():
            direction[free] = np.linalg.solve(hessian[np.ix_(free, free)], -gradient[free])
        if np.max(np.abs(direction)) < 1e-10:
            # At a bound, release a joint if moving back into its range would
            # reduce the objective; otherwise the constrained solution is done.
            violation = np.where(active != 0, active * gradient, -np.inf)
            index = int(np.argmax(violation))
            if violation[index] <= 1e-10:
                return np.clip(velocity, lower, upper)
            active[index] = 0
            continue
        ratios = np.full(count, np.inf)
        positive, negative = direction > 1e-12, direction < -1e-12
        ratios[positive] = (upper[positive] - velocity[positive]) / direction[positive]
        ratios[negative] = (lower[negative] - velocity[negative]) / direction[negative]
        index = int(np.argmin(ratios))
        fraction = max(0.0, min(1.0, ratios[index]))
        velocity += fraction * direction
        if fraction < 1:
            active[index] = 1 if direction[index] > 0 else -1
    # Do not send an unconverged solution to the motion planner.
    return np.zeros(count)


class CartesianTrajectory:
    """Locally refreshed velocity trajectory with a bounded command lifetime."""

    def __init__(self, position, speed, limits=JOINT_LIMITS):
        self.limits = np.asarray(limits, dtype=float)
        count = len(position)
        self.generator = Ruckig(count, 0.001)
        self.input, self.output = InputParameter(count), OutputParameter(count)
        self.input.control_interface = ControlInterface.Velocity
        # Keep the IK joint ratios together through acceleration and braking.
        # Independent ramps distort tool direction, especially at high speeds.
        self.input.synchronization = Synchronization.Phase
        self.input.current_position = list(position)
        self.input.current_velocity = self.input.current_acceleration = [0.0] * count
        self.input.target_velocity = self.input.target_acceleration = [0.0] * count
        self.input.max_velocity = [speed] * count
        # Teleoperation must respond to release/reversal promptly, including
        # at 100% speed. Keep jerk-limited ramps, but avoid the multi-second
        # braking tail of the slower point-to-point Home profile.
        self.input.max_acceleration = [np.rad2deg(1.0)] * count
        self.input.max_jerk = [np.rad2deg(10.0)] * count
        self.speed = speed
        self.command = None
        self.deadline = 0
        self.stopping = False
        self.stop_reason = None
        self.finished = False

    def request(self, command, now):
        if self.stopping:
            raise ValueError("Franka is stopping; release input before resuming")
        # Allow one accepted command's 300 ms transport window plus a refresh
        # and render-scheduling margin. Explicit release still stops at once;
        # this deadline is only the simulator's lost-input fallback.
        self.command, self.deadline = command, now + 0.5

    def stop(self, reason="released"):
        if not self.stopping:
            self.stop_reason = reason
        self.stopping = True
        self.command = None

    def advance(self, position, jacobian, elapsed, now):
        if now > self.deadline:
            self.stop("input expired")
        if self.command is not None:
            # Never keep integrating a target if physics fails to follow it.
            # The scene's damped position drives lag during motion. Allow a
            # bounded 300 ms of commanded travel plus the static load offset.
            tolerance = 3 + 0.3 * self.speed
            if np.max(np.abs(np.asarray(self.input.current_position) - position)) > tolerance:
                self.stop("joint tracking error")
        velocity = (
            joint_velocity(jacobian, position, **self.command, speed=self.speed, limits=self.limits)
            if self.command is not None
            else [0.0] * len(position)
        )
        self.input.target_velocity = velocity
        self.generator.delta_time = elapsed
        result = self.generator.update(self.input, self.output)
        if result < Result.Working:
            raise RuntimeError(f"Franka Cartesian trajectory failed: {result}")
        self.finished = self.stopping and result == Result.Finished
        self.output.pass_to_input(self.input)
        return np.clip(self.output.new_position, self.limits[:, 0], self.limits[:, 1]).tolist()
