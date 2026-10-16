# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA differential kinematics from the loaded USD and measured joint angles."""

import time

import numpy as np
from telesurgery_robots.mira.poses import MIRA_SIM_HOME
from telesurgery_sim.runtime.franka import rotation_matrix


def elbow_angle(position, direction, arm):
    sweep = np.arctan2(position[0], -position[2])
    x = np.cos(sweep) * direction[0] + np.sin(sweep) * direction[2]
    return float(np.rad2deg(np.arctan2(direction[1], x)) * (-1 if arm == "left" else 1))


class MiraFeedback:
    """Use USD joint frames, including the asset's scale, without duplicating vendor IK."""

    def __init__(self, stage, drives):
        from pxr import Gf, Usd, UsdGeom, UsdPhysics

        cache = UsdGeom.XformCache()
        mm = UsdGeom.GetStageMetersPerUnit(stage) * 1000
        self.chains, self.limits = {}, {}
        self.kinematics = None

        def frame(joint, side):
            body = stage.GetPrimAtPath(getattr(joint, f"GetBody{side}Rel")().GetTargets()[0])
            world = cache.GetLocalToWorldTransform(body)
            local = getattr(joint, f"GetLocalPos{side}Attr")().Get()
            rotation = getattr(joint, f"GetLocalRot{side}Attr")().Get()
            body_rotation = Gf.Transform(world).GetRotation().GetQuat()
            result = np.eye(4)
            result[:3, :3] = rotation_matrix(
                [body_rotation.GetReal(), *body_rotation.GetImaginary()]
            ) @ rotation_matrix([rotation.GetReal(), *rotation.GetImaginary()])
            result[:3, 3] = np.asarray(world.Transform(Gf.Vec3d(local))) * mm
            return result

        for arm, joints in drives.items():
            self.chains[arm] = []
            self.limits[arm] = []
            previous = None
            for index in range(6):
                joint = UsdPhysics.RevoluteJoint(joints[index].GetPrim())
                before, after = frame(joint, 0), frame(joint, 1)
                if previous is None:
                    body = stage.GetPrimAtPath(joint.GetBody0Rel().GetTargets()[0])
                    world = cache.GetLocalToWorldTransform(body)
                    q = Gf.Transform(world).GetRotation().GetQuat()
                    previous = np.eye(4)
                    previous[:3, :3] = rotation_matrix([q.GetReal(), *q.GetImaginary()])
                    previous[:3, 3] = np.asarray(world.ExtractTranslation()) * mm
                self.chains[arm].append(
                    (np.linalg.inv(previous) @ before, "XYZ".index(joint.GetAxisAttr().Get()))
                )
                previous = after
                if index < 4:
                    self.limits[arm].append(
                        (joint.GetLowerLimitAttr().Get(), joint.GetUpperLimitAttr().Get())
                    )
            # Control a grasp point near the distal jaws, not the jaw hinge.
            # The asset scales its tools and reverses the right tool's pointing
            # axis. Derive both distance and sign from its inner jaw surfaces.
            roll = UsdPhysics.RevoluteJoint(joints[4].GetPrim())
            roll_frame = frame(roll, 1)
            axis = "XYZ".index(roll.GetAxisAttr().Get())
            tool = stage.GetPrimAtPath(roll.GetBody1Rel().GetTargets()[0]).GetParent()
            distances = []
            for prim in Usd.PrimRange(tool):
                if not prim.IsA(UsdGeom.Mesh) or not prim.GetName().endswith("_inner"):
                    continue
                points = np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get())
                world = np.c_[points, np.ones(len(points))] @ np.asarray(
                    cache.GetLocalToWorldTransform(prim)
                )
                local = (world[:, :3] * mm - roll_frame[:3, 3]) @ roll_frame[:3, :3]
                distances.extend((local[:, axis].min(), local[:, axis].max()))
            if not distances:
                raise RuntimeError(f"MIRA {arm} tool has no inner jaw geometry")
            offset = np.eye(4)
            offset[axis, 3] = 0.97 * max(distances, key=abs)
            self.chains[arm][-1] = offset, axis
        self.workspace = {arm: self.workspace_bounds(arm) for arm in self.chains}

    def pose(self, arm, joints):
        transform = np.eye(4)
        for index, (offset, axis) in enumerate(self.chains[arm]):
            transform = transform @ offset
            if index == 5:
                break  # Grasp point on the tool centerline, independent of jaw opening.
            angle = np.deg2rad(joints[index])
            direction = np.eye(3)[axis]
            skew = np.array(
                [
                    [0, -direction[2], direction[1]],
                    [direction[2], 0, -direction[0]],
                    [-direction[1], direction[0], 0],
                ]
            )
            rotation = np.eye(4)
            rotation[:3, :3] = (
                np.eye(3) + np.sin(angle) * skew + (1 - np.cos(angle)) * (skew @ skew)
            )
            transform = transform @ rotation
            if index == 4:
                tool_axis = transform[:3, :3] @ direction
        position = transform[:3, 3]
        return np.array([*position, elbow_angle(position, tool_axis, arm)])

    def jacobian(self, arm, joints, pose):
        result = np.empty((4, 4))
        for index in range(4):
            shifted = joints.copy()
            shifted[index] += 0.001
            difference = self.pose(arm, shifted) - pose
            difference[3] = (difference[3] + 180) % 360 - 180
            result[:, index] = difference / 0.001
        return result

    def workspace_bounds(self, arm):
        """Calibrate axis travel from Home using this asset's geometry and joint limits.

        These are operating extents, not a claim that every box corner is
        reachable. The local follower also enforces the current joint limits.
        """
        home = np.array([*MIRA_SIM_HOME[arm], 0.0])
        center = self.pose(arm, home)
        limits = np.asarray(self.limits[arm])
        lower, upper = center[:3].copy(), center[:3].copy()
        for axis in range(3):
            for sign in (-1, 1):
                q, target, pose = home.copy(), center.copy(), center.copy()
                for _ in range(600):
                    target[axis] += sign * 2
                    error = target - pose
                    error[3] = (error[3] + 180) % 360 - 180
                    jacobian = self.jacobian(arm, q, pose)
                    change = np.linalg.lstsq(jacobian, error, rcond=1e-3)[0]
                    next_q = q[:4] + change
                    if (
                        np.max(np.abs(change)) > 3
                        or np.linalg.norm(jacobian @ change - error) > 0.1
                        or np.any(next_q < limits[:, 0] + 0.5)
                        or np.any(next_q > limits[:, 1] - 0.5)
                    ):
                        break
                    q[:4] = next_q
                    pose = self.pose(arm, q)
                    if np.linalg.norm(pose[:3] - target[:3]) > 0.5:
                        break
                    (lower if sign < 0 else upper)[axis] = pose[axis]
        return {"min": lower.tolist(), "max": upper.tolist()}

    def read(self, measured, *, idle=True):
        self.kinematics = None
        if not all(arm in measured.get("joints_deg", {}) for arm in self.chains):
            return {}
        result = {}
        for arm in self.chains:
            joints = np.asarray(measured["joints_deg"][arm], dtype=float)
            pose = self.pose(arm, joints)
            jacobian = self.jacobian(arm, joints, pose)
            result[arm] = (joints, pose, jacobian, self.limits[arm])
        self.kinematics = (result, time.monotonic())
        return {
            "cartesian_workspace": {
                arm: {
                    "frame": "MIRA simulation base",
                    "unit": "m",
                    **{key: [v / 1000 for v in row] for key, row in bounds.items()},
                }
                for arm, bounds in self.workspace.items()
            },
            "cartesian_mm_deg": {arm: data[1].tolist() for arm, data in result.items()},
            "mira_workspace_mm": self.workspace,
        }
