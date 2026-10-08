# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physics feedback follows USD joint identity, never drive order or target values."""

from types import SimpleNamespace

import numpy as np
import pytest
from telesurgery_robots.simulation.state import SimRobot
from telesurgery_sim.runtime.feedback import JointFeedback


def view(paths, positions, velocities, *, valid=True):
    return SimpleNamespace(
        dof_paths=[paths],
        is_physics_tensor_entity_valid=lambda: valid,
        get_dof_positions=lambda: SimpleNamespace(numpy=lambda: np.deg2rad([positions])),
        get_dof_velocities=lambda: SimpleNamespace(numpy=lambda: np.deg2rad([velocities])),
    )


def test_measured_joints_follow_paths_across_articulations():
    feedback = JointFeedback.__new__(JointFeedback)
    feedback.groups = {"left": ["/L1", "/L2"], "right": ["/R1", "/R2"]}
    feedback.grippers = {"left": "/grip"}
    feedback.views = [
        view(["/R2", "/R1"], [24, 13], [4, 3]),
        view(["/L2", "/grip", "/L1"], [22, 45, 11], [2, 9, 1]),
    ]
    state = feedback.read()
    assert state["joints_deg"]["left"] == pytest.approx([11, 22])
    assert state["joints_deg"]["right"] == pytest.approx([13, 24])
    assert state["velocity_deg_s"]["left"] == pytest.approx([1, 2])
    assert state["velocity_deg_s"]["right"] == pytest.approx([3, 4])
    assert state["grippers_deg"]["left"] == pytest.approx(45)
    robot = SimRobot()
    targets = robot.apply({"method": "get_state"})["targets_deg"]
    robot.feedback = state
    published = robot.apply({"method": "get_state"})
    assert published["targets_deg"] == targets
    assert published["joints_deg"] == state["joints_deg"]


def test_feedback_waits_for_physics_and_rejects_missing_joint():
    feedback = JointFeedback.__new__(JointFeedback)
    feedback.groups = {"joints": ["/J1", "/J2"]}
    feedback.grippers = {}
    feedback.views = [view(["/J1"], [1], [0], valid=False)]
    assert feedback.read() == {}
    feedback.views = [view(["/J1"], [1], [0])]
    with pytest.raises(RuntimeError, match="/J2"):
        feedback.read()
