# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA differential kinematics from the loaded USD and measured joint angles."""

import time

import numpy as np
from telesurgery_sim.runtime.franka import rotation_matrix


def elbow_angle(position, direction, arm):
    sweep = np.arctan2(position[0], -position[2])
    x = np.cos(sweep) * direction[0] + np.sin(sweep) * direction[2]
    return float(np.rad2deg(np.arctan2(direction[1], x)) * (-1 if arm == "left" else 1))


class MiraFeedback:
    """Use USD joint frames, including the asset's scale, without duplicating vendor IK."""

    def __init__(self, stage, drives):
        from pxr import Gf, UsdGeom, UsdPhysics

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

    def pose(self, arm, joints):
        transform = np.eye(4)
        for index, (offset, axis) in enumerate(self.chains[arm]):
            transform = transform @ offset
            if index == 5:
                break  # Jaw pivot, independent of jaw opening.
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

    def read(self, measured):
        self.kinematics = None
        if not all(arm in measured.get("joints_deg", {}) for arm in self.chains):
            return {}
        result = {}
        for arm in self.chains:
            joints = np.asarray(measured["joints_deg"][arm], dtype=float)
            pose = self.pose(arm, joints)
            jacobian = np.empty((4, 4))
            for index in range(4):
                shifted = joints.copy()
                shifted[index] += 0.001
                difference = self.pose(arm, shifted) - pose
                difference[3] = (difference[3] + 180) % 360 - 180
                jacobian[:, index] = difference / 0.001
            result[arm] = (joints, pose, jacobian, self.limits[arm])
        self.kinematics = (result, time.monotonic())
        return {"cartesian_mm_deg": {arm: data[1].tolist() for arm, data in result.items()}}
