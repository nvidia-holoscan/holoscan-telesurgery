# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Restore a MIRA scene on the physics thread without rebuilding cameras."""

import numpy as np


class SceneReset:
    def __init__(self, stage, feedback, drives, initial, dynamic_roots):
        from isaacsim.core.experimental.prims import RigidPrim
        from pxr import Usd, UsdPhysics

        self.articulations = []
        # Preserve auxiliary DOFs such as MIRA's coupled second jaw. They do
        # not have an independent controller drive, but PhysX still lists them.
        self.positions = {
            str(prim.GetPath()): np.deg2rad(
                prim.GetAttribute("state:angular:physics:position").Get() or 0.0
            )
            for prim in stage.Traverse()
            if prim.IsA(UsdPhysics.RevoluteJoint)
        }
        self.positions.update(
            {
                str(drive.GetPath()): np.deg2rad(initial[arm][index])
                for arm, joints in drives.items()
                for index, drive in joints.items()
            }
        )
        for view in feedback.views:
            pose = tuple(value.numpy().copy() for value in view.get_world_poses())
            self.articulations.append((view, pose))
        self.props = []
        for root in dynamic_roots:
            for prim in Usd.PrimRange(stage.GetPrimAtPath(root)):
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    view = RigidPrim(str(prim.GetPath()), reset_xform_op_properties=False)
                    pose = tuple(value.numpy().copy() for value in view.get_world_poses())
                    self.props.append((view, pose))

    def restore(self):
        if not all(
            view.is_physics_tensor_entity_valid() for view, _ in (*self.articulations, *self.props)
        ):
            raise ValueError("Scene physics is not ready to reset")
        # Teleport both pose and velocity; resetting only drive targets would
        # leave a dropped needle and residual momentum in the old episode.
        for view, pose in self.articulations:
            # PhysX can order DOFs differently from the pre-play USD backend.
            joints = np.array([[self.positions[path] for path in view.dof_paths[0]]])
            view.set_world_poses(*pose)
            view.set_velocities(
                linear_velocities=np.zeros((1, 3), dtype=np.float32),
                angular_velocities=np.zeros((1, 3), dtype=np.float32),
            )
            view.set_dof_positions(joints)
            view.set_dof_velocities(np.zeros_like(joints))
        for view, pose in self.props:
            view.set_world_poses(*pose)
            view.set_velocities(
                linear_velocities=np.zeros((1, 3), dtype=np.float32),
                angular_velocities=np.zeros((1, 3), dtype=np.float32),
            )
