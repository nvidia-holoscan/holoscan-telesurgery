# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Include MIRA's tool rolls in the arm articulation and measured feedback."""

from telesurgery_robots.mira.poses import MIRA_ROLL_LIMIT


def enable_tool_roll(stage):
    from pxr import UsdPhysics

    for prim in stage.Traverse():
        if prim.GetName() not in {"LJ5_joint", "RJ5_joint"}:
            continue
        joint = UsdPhysics.RevoluteJoint(prim)
        if not joint:
            raise RuntimeError(f"Expected a revolute tool joint: {prim.GetPath()}")
        joint.CreateExcludeFromArticulationAttr(False)
        joint.CreateLowerLimitAttr(-MIRA_ROLL_LIMIT)
        joint.CreateUpperLimitAttr(MIRA_ROLL_LIMIT)
        # The asset gives each detached tool its own root. Once connected to the
        # arm, its joints belong to the robot's existing base articulation.
        tool_root = prim.GetParent().GetParent()
        if tool_root.HasAPI(UsdPhysics.ArticulationRootAPI):
            tool_root.RemoveAPI(UsdPhysics.ArticulationRootAPI)
