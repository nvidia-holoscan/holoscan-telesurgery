# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physics feedback follows USD joint identity, never drive order or target values."""

from types import SimpleNamespace

import numpy as np
import pytest
from telesurgery_robots.simulation.state import SimRobot
from telesurgery_sim.runtime.feedback import JointFeedback
from telesurgery_sim.runtime.franka import FrankaFeedback, rotation_matrix


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


def test_drive_targets_use_physics_joint_identity_and_leave_mimic_joint_alone():
    feedback = JointFeedback.__new__(JointFeedback)
    commands = []
    first = view(["/R2", "/mimic", "/L1"], [0, 0, 0], [0, 0, 0])
    second = view(["/finger", "/L2"], [0, 0], [0, 0])
    for number, item in enumerate((first, second)):
        item.set_dof_position_targets = lambda values, dof_indices, n=number: commands.append(
            (n, "position", values, dof_indices)
        )
        item.set_dof_velocity_targets = lambda values, dof_indices, n=number: commands.append(
            (n, "velocity", values, dof_indices)
        )
    feedback.views = [first, second]
    feedback.apply_targets({"/L1": 0.1, "/L2": 0.2, "/R2": 0.3, "/finger": 0.025}, {"/L1": 0.4})
    assert commands == [
        (0, "position", [0.3, 0.1], [0, 2]),
        (0, "velocity", [0.4], [2]),
        (1, "position", [0.025, 0.2], [0, 1]),
    ]
    commands.clear()
    with pytest.raises(RuntimeError, match="/missing"):
        feedback.apply_targets({"/L1": 0.5, "/missing": 0.6})
    assert commands == []


@pytest.mark.parametrize("yaw", [0, 90, 180, 270])
@pytest.mark.parametrize("tool_yaw", [0, 45, 180])
def test_franka_tool_jacobian_uses_joint_identity_and_rotated_base(monkeypatch, yaw, tool_yaw):
    monkeypatch.setattr("time.monotonic", lambda: 123)
    feedback = FrankaFeedback.__new__(FrankaFeedback)
    feedback.hand, feedback.tool_name = 2, "TCP"
    feedback.joint_paths = [f"/J{i}" for i in range(7)]
    feedback.finger_paths = []
    feedback.kinematics = None
    # The USD articulation's order differs from the controller's joint order.
    paths = list(reversed(feedback.joint_paths))
    jacobian = np.arange(42).reshape(6, 7)
    tensors = np.zeros((1, 2, 6, 7))
    tensors[0, 1] = jacobian[:, ::-1]
    feedback.view = SimpleNamespace(
        is_physics_tensor_entity_valid=lambda: True,
        dof_paths=[paths],
        num_links=3,
        num_dofs=7,
        get_jacobian_matrices=lambda: SimpleNamespace(numpy=lambda: tensors),
        get_dof_positions=lambda: SimpleNamespace(numpy=lambda: np.zeros((1, 7))),
    )
    # CMR's opposing bases must each retain their own axes. Rotating the tool
    # must not rotate the jog reference with it.
    angle, tool_angle = np.deg2rad([yaw, tool_yaw]) / 2
    quaternion = np.array([np.cos(angle), 0, 0, np.sin(angle)])
    tool_quaternion = np.array([np.cos(tool_angle), 0, 0, np.sin(tool_angle)])
    base = rotation_matrix(quaternion)
    origin = np.array([1, 2, 3])
    feedback.frames = SimpleNamespace(
        get_world_poses=lambda: (
            SimpleNamespace(numpy=lambda: np.array([origin, origin + base @ [0.5, 0, 0]])),
            SimpleNamespace(numpy=lambda: np.array([quaternion, tool_quaternion])),
        )
    )
    measured = {"joints_deg": {"joints": list(range(7))}}
    state = feedback.read(measured)
    np.testing.assert_allclose(state["tool_pose"]["position_m"], [0.5, 0, 0], atol=1e-12)
    np.testing.assert_allclose(
        state["tool_pose"]["orientation_matrix"],
        base.T @ rotation_matrix(tool_quaternion),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        feedback.kinematics[1], np.vstack((base.T @ jacobian[:3], base.T @ jacobian[3:]))
    )
    assert feedback.kinematics[2] == 123
    assert "grippers" not in state
    feedback.view.is_physics_tensor_entity_valid = lambda: False
    assert feedback.read(measured) == {}
    assert feedback.kinematics is None


def test_scene_reset_restores_robot_props_and_zeroes_momentum():
    from unittest.mock import Mock

    from telesurgery_sim.runtime.reset import SceneReset

    scene = SceneReset.__new__(SceneReset)
    arm, needle = Mock(), Mock()
    arm_pose = (np.array([[0, 1, 2]]), np.array([[1, 0, 0, 0]]))
    needle_pose = (np.array([[3, 4, 5]]), np.array([[0, 1, 0, 0]]))
    joints = np.deg2rad([[25, 68, 49, 92, 0, 0.3]])
    arm.dof_paths = [[f"/J{i}" for i in range(6)]]
    scene.positions = dict(zip(arm.dof_paths[0], joints[0], strict=True))
    scene.articulations = [(arm, arm_pose)]
    scene.props = [(needle, needle_pose)]
    scene.restore()
    np.testing.assert_array_equal(arm.set_dof_positions.call_args.args[0], joints)
    np.testing.assert_array_equal(arm.set_dof_velocities.call_args.args[0], np.zeros_like(joints))
    for view, pose in ((arm, arm_pose), (needle, needle_pose)):
        for actual, expected in zip(view.set_world_poses.call_args.args, pose, strict=True):
            np.testing.assert_array_equal(actual, expected)
        velocities = view.set_velocities.call_args.kwargs
        assert set(velocities) == {"linear_velocities", "angular_velocities"}
        for value in velocities.values():
            np.testing.assert_array_equal(value, np.zeros((1, 3)))
    needle.is_physics_tensor_entity_valid.return_value = False
    arm.reset_mock()
    with pytest.raises(ValueError, match="not ready"):
        scene.restore()
    arm.set_dof_positions.assert_not_called()
