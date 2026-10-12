# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Simulation uses the same Ruckig position/stop profiles as the native Franka loop."""

import math

from ruckig import (
    ControlInterface,
    InputParameter,
    OutputParameter,
    Result,
    Ruckig,
    Synchronization,
)


class JointTrajectory:
    def __init__(self, position, goal, speed):
        count = len(position)
        self.generator = Ruckig(count, 0.001)
        self.input, self.output = InputParameter(count), OutputParameter(count)
        self.input.current_position = list(position)
        self.input.current_velocity = self.input.current_acceleration = [0.0] * count
        self.input.target_position = list(goal)
        self.input.target_velocity = self.input.target_acceleration = [0.0] * count
        self.input.max_velocity = [speed] * count
        self.input.max_acceleration = [math.degrees(0.2)] * count
        self.input.max_jerk = [math.degrees(2.0)] * count
        self.input.synchronization = Synchronization.Time
        self.generator.calculate(self.input, self.output.trajectory)
        self.duration = self.output.trajectory.duration
        self.finished = False

    def target(self, goal):
        self.input.target_position = list(goal)

    def stop(self):
        self.input.control_interface = ControlInterface.Velocity
        self.input.synchronization = Synchronization.No

    def advance(self, elapsed):
        self.generator.delta_time = elapsed
        result = self.generator.update(self.input, self.output)
        if result < Result.Working:
            raise RuntimeError(f"Franka trajectory failed: {result}")
        self.finished = result == Result.Finished
        self.output.pass_to_input(self.input)
        return list(self.output.new_position)
