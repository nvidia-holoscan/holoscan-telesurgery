# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Franka tool pose and differential kinematics from live PhysX tensors."""

import time

import numpy as np
from telesurgery_robots.workspace import SerialModel, Workspace, axis_bounds


def rotation_matrix(quaternion):
    w, x, y, z = np.asarray(quaternion) / np.linalg.norm(quaternion)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


class FrankaFeedback:
    def __init__(self, feedback, fingers):
        from isaacsim.core.experimental.prims import RigidPrim

        if len(feedback.views) != 1:
            raise RuntimeError("Franka Cartesian control requires one articulation")
        self.view = feedback.views[0]
        self.tool_name = "TCP" if "TCP" in self.view.link_names else "panda_hand"
        self.hand = self.view.link_names.index(self.tool_name)
        self.frames = RigidPrim(
            [
                self.view.link_paths[0][0],
                self.view.link_paths[0][self.hand],
            ]
        )
        self.joint_paths = feedback.groups["joints"]
        self.finger_paths = [str(drive.GetPath()) for drive in fingers.values()]
        self.kinematics = None
        self.workspace = Workspace()

    def read(self, measured, *, idle=True):
        if not self.view.is_physics_tensor_entity_valid() or "joints_deg" not in measured:
            self.kinematics = None
            self.workspace.close()
            return {}
        paths = self.view.dof_paths[0]
        joints = [paths.index(path) for path in self.joint_paths]
        jacobians = self.view.get_jacobian_matrices().numpy()[0]
        if jacobians.shape != (self.view.num_links - 1, 6, self.view.num_dofs):
            raise RuntimeError("Franka Cartesian control requires a fixed robot base")
        jacobian_world = jacobians[self.hand - 1][:, joints]
        positions, quaternions = (v.numpy() for v in self.frames.get_world_poses())
        base_rotation = rotation_matrix(quaternions[0])
        hand_rotation = rotation_matrix(quaternions[1])
        jacobian = np.vstack(
            (
                base_rotation.T @ jacobian_world[:3],
                base_rotation.T @ jacobian_world[3:],
            )
        )
        self.kinematics = (
            np.asarray(measured["joints_deg"]["joints"]),
            jacobian,
            time.monotonic(),
        )
        dofs = self.view.get_dof_positions().numpy()[0]
        fingers = [float(dofs[paths.index(path)]) for path in self.finger_paths]
        position = base_rotation.T @ (positions[1] - positions[0])
        orientation = base_rotation.T @ hand_rotation
        q = np.deg2rad(self.kinematics[0])
        # Read limits and chain geometry from the loaded articulation. The same
        # provider covers Franka and every Versius arm, including rotated bases.
        limits = np.column_stack([v.numpy()[0][joints] for v in self.view.get_dof_limits()])
        bounds = self.workspace.update(
            position,
            orientation,
            lambda cancelled: axis_bounds(
                SerialModel(q, position, orientation, jacobian), q, limits, cancelled
            ),
            idle=idle,
        )
        return {
            "cartesian_workspace": {"hand": bounds} if bounds else {},
            "workspace_error": self.workspace.error,
            "tool_pose": {
                "frame": "base",
                "end_effector": self.tool_name,
                "position_m": position.tolist(),
                "orientation_matrix": orientation.tolist(),
            },
            **(
                {
                    "grippers": {"hand": float(np.clip(np.mean(fingers) / 0.04, 0, 1))},
                    "gripper_width_m": sum(fingers),
                }
                if fingers
                else {}
            ),
        }
