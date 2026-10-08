# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read actual articulated joint positions after an Isaac Sim physics step."""

import numpy as np


class JointFeedback:
    def __init__(self, stage, root, drives, joint_count, *, gripper_joints=None):
        from isaacsim.core.experimental.prims import Articulation
        from pxr import Usd, UsdPhysics

        self.views = []
        for prim in Usd.PrimRange(stage.GetPrimAtPath(root)):
            if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
                view = Articulation(str(prim.GetPath()))
                if view.num_dofs:
                    self.views.append(view)
        self.groups = {
            group: [str(joints[index].GetPath()) for index in range(joint_count)]
            for group, joints in drives.items()
        }
        self.grippers = gripper_joints or {}

    def read(self):
        # Tensor views become available only after physics starts.
        if not self.views or not all(v.is_physics_tensor_entity_valid() for v in self.views):
            return {}
        positions, velocities = {}, {}
        for view in self.views:
            paths = view.dof_paths[0]
            positions.update(
                zip(paths, np.rad2deg(view.get_dof_positions().numpy()[0]), strict=True)
            )
            velocities.update(
                zip(paths, np.rad2deg(view.get_dof_velocities().numpy()[0]), strict=True)
            )
        missing = (
            {path for paths in self.groups.values() for path in paths} | set(self.grippers.values())
        ) - positions.keys()
        if missing:
            raise RuntimeError(f"Simulator joints missing from physics feedback: {sorted(missing)}")
        return {
            "joints_deg": {
                group: [float(positions[path]) for path in paths]
                for group, paths in self.groups.items()
            },
            "velocity_deg_s": {
                group: [float(velocities[path]) for path in paths]
                for group, paths in self.groups.items()
            },
            "feedback_source": "Isaac Sim physics state",
            **(
                {
                    "grippers_deg": {
                        arm: float(positions[path]) for arm, path in self.grippers.items()
                    }
                }
                if self.grippers
                else {}
            ),
        }
