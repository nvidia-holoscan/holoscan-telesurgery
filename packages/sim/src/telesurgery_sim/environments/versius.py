# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build three instrument arms and one camera arm from local Versius assets."""

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from telesurgery_robots.versius import HOME, LIMITS


def build(stage, directory):
    import trimesh
    from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics, UsdShade, Vt

    directory = Path(directory)
    material = UsdShade.Material.Define(stage, "/World/JawContactMaterial")
    physics = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(1.0)
    physics.CreateDynamicFrictionAttr(0.8)
    physics.CreateRestitutionAttr(0)
    for name in ("BSU.urdf", "needle_holder_platform.urdf", "fenestrated_grasper_platform.urdf"):
        if not (directory / name).is_file():
            raise FileNotFoundError(
                f"Extract the supplied CMR Versius URDF archive into {directory}: missing {name}"
            )

    def rotation(rpy):
        r, p, y = np.rad2deg(rpy)
        return (
            Gf.Rotation(Gf.Vec3d(0, 0, 1), y)
            * Gf.Rotation(Gf.Vec3d(0, 1, 0), p)
            * Gf.Rotation(Gf.Vec3d(1, 0, 0), r)
        )

    def origin(xml):
        xyz = (
            np.array([float(v) for v in xml.get("xyz", "0 0 0").split()])
            if xml is not None
            else np.zeros(3)
        )
        rpy = (
            np.array([float(v) for v in xml.get("rpy", "0 0 0").split()])
            if xml is not None
            else np.zeros(3)
        )
        return Gf.Matrix4d().SetRotate(rotation(rpy)).SetTranslateOnly(Gf.Vec3d(*xyz))

    def place(path, matrix):
        xform = UsdGeom.Xform.Define(stage, path)
        xform.AddTransformOp().Set(matrix)
        return xform.GetPrim()

    def model(root, source, initial, *, parent=None, attachment=None):
        # Only locally installed vendor URDFs are accepted; no network XML input.
        xml = ET.parse(directory / source).getroot()  # nosec B314
        joints = list(xml.findall("joint"))
        transforms = {"world": Gf.Matrix4d(1)}
        # URDF's frame-only links remain in the chain, including zero-mass J7.
        remaining = list(joints)
        while remaining:
            count = len(remaining)
            for joint in remaining[:]:
                before, after = joint.find("parent").get("link"), joint.find("child").get("link")
                if before not in transforms:
                    continue
                matrix = origin(joint.find("origin"))
                if joint.get("type") == "revolute":
                    axis = Gf.Vec3d(*map(float, joint.find("axis").get("xyz").split()))
                    matrix = (
                        Gf.Matrix4d().SetRotate(
                            Gf.Rotation(axis, initial.get(joint.get("name"), 0))
                        )
                        * matrix
                    )
                transforms[after] = matrix * transforms[before]
                remaining.remove(joint)
            if len(remaining) == count:
                raise ValueError("Versius URDF has a disconnected joint tree")
        for link in xml.findall("link"):
            name = link.get("name")
            if name == "world" or name.startswith("DH_"):
                continue
            prim = place(f"{root}/{name}", transforms[name])
            UsdPhysics.RigidBodyAPI.Apply(prim)
            PhysxSchema.PhysxRigidBodyAPI.Apply(prim).CreateDisableGravityAttr(True)
            inertia = link.find("inertial")
            mass = float(inertia.find("mass").get("value")) if inertia is not None else 0.02
            UsdPhysics.MassAPI.Apply(prim).CreateMassAttr(
                max(mass, 0.0001 if name.startswith("jaw") else 0.02)
            )
            for index, visual in enumerate(link.findall("visual")):
                base = f"{root}/{name}/visual_{index}"
                place(base, origin(visual.find("origin")))
                mesh = visual.find("geometry/mesh")
                path = (directory / mesh.get("filename")).resolve()
                if not path.is_relative_to(directory.resolve()):
                    raise ValueError(
                        "Versius mesh path must stay within the supplied asset directory"
                    )
                scene = trimesh.load_scene(path, process=False)
                color = visual.find("material/color")
                rgba = (
                    list(map(float, color.get("rgba").split())) if color is not None else [0.7] * 4
                )
                for number, node in enumerate(scene.graph.nodes_geometry):
                    matrix, geometry = scene.graph[node]
                    data = scene.geometry[geometry].copy()
                    data.apply_transform(matrix)
                    surface = UsdGeom.Mesh.Define(stage, f"{base}/mesh_{number}")
                    surface.CreatePointsAttr(
                        Vt.Vec3fArray.FromNumpy(np.asarray(data.vertices, np.float32))
                    )
                    surface.CreateFaceVertexCountsAttr(
                        Vt.IntArray.FromNumpy(np.full(len(data.faces), 3, np.int32))
                    )
                    surface.CreateFaceVertexIndicesAttr(
                        Vt.IntArray.FromNumpy(np.asarray(data.faces, np.int32).ravel())
                    )
                    surface.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
                    surface.CreateDisplayColorAttr([Gf.Vec3f(*rgba[:3])])
                    surface.CreateNormalsAttr(
                        Vt.Vec3fArray.FromNumpy(np.asarray(data.vertex_normals, np.float32))
                    )
                    surface.SetNormalsInterpolation(UsdGeom.Tokens.vertex)
                    # Original URDFs have no collisions. Convex hulls provide
                    # contact geometry for this simulation's instrument jaws.
                    if name.startswith("jaw"):
                        UsdPhysics.CollisionAPI.Apply(surface.GetPrim())
                        contact = PhysxSchema.PhysxCollisionAPI.Apply(surface.GetPrim())
                        contact.CreateContactOffsetAttr(0.0002)
                        contact.CreateRestOffsetAttr(0.0)
                        contact.CreateTorsionalPatchRadiusAttr(0.00025)
                        contact.CreateMinTorsionalPatchRadiusAttr(0.0001)
                        UsdShade.MaterialBindingAPI.Apply(surface.GetPrim()).Bind(
                            material, materialPurpose="physics"
                        )
                        UsdPhysics.MeshCollisionAPI.Apply(
                            surface.GetPrim()
                        ).CreateApproximationAttr("convexHull")
        drives = {}
        for joint in joints:
            name, kind = joint.get("name"), joint.get("type")
            before, after = joint.find("parent").get("link"), joint.find("child").get("link")
            if after.startswith("DH_"):
                continue  # Reference frames have no dynamic role.
            path = f"{root}/joints/{name}"
            api = (
                UsdPhysics.RevoluteJoint.Define(stage, path)
                if kind == "revolute"
                else UsdPhysics.FixedJoint.Define(stage, path)
            )
            matrix = origin(joint.find("origin"))
            if before == "world":
                if parent:
                    api.CreateBody0Rel().SetTargets([parent])
                    matrix = attachment * matrix
                else:
                    matrix = transforms[after] * UsdGeom.XformCache().GetLocalToWorldTransform(
                        stage.GetPrimAtPath(root)
                    )
            else:
                api.CreateBody0Rel().SetTargets([f"{root}/{before}"])
            api.CreateBody1Rel().SetTargets([f"{root}/{after}"])
            orientation = matrix.ExtractRotationQuat()
            if kind == "revolute":
                axis = Gf.Vec3d(*map(float, joint.find("axis").get("xyz").split()))
                alignment = Gf.Rotation(Gf.Vec3d(1, 0, 0), axis).GetQuat()
                api.CreateAxisAttr("X")
                api.CreateLocalRot0Attr(Gf.Quatf(orientation * alignment))
                api.CreateLocalRot1Attr(Gf.Quatf(alignment))
                # BSU numbers are degrees; missing instrument limits are
                # explicit demonstration limits, never physical specifications.
                limits = joint.find("limit")
                lo, hi = (
                    (float(limits.get("lower")), float(limits.get("upper")))
                    if limits is not None
                    else (-60, 60)
                )
                api.CreateLowerLimitAttr(lo)
                api.CreateUpperLimitAttr(hi)
                drive = UsdPhysics.DriveAPI.Apply(api.GetPrim(), "angular")
                drive.CreateTypeAttr("acceleration")
                drive.CreateStiffnessAttr(1600)
                drive.CreateDampingAttr(80)
                drive.CreateMaxForceAttr(100)
                drive.CreateTargetPositionAttr(initial.get(name, 0))
                drive.CreateTargetVelocityAttr(0)
                PhysxSchema.PhysxJointAPI.Apply(api.GetPrim()).CreateArmatureAttr(0.01)
                if after.startswith("jaw"):
                    # Bounded jaw force, with a small closing preload retained
                    # after input release. These are training settings, not
                    # supplied hardware ratings.
                    drive.CreateTypeAttr("force")
                    drive.CreateStiffnessAttr(0.002)
                    drive.CreateDampingAttr(0.00002)
                    drive.CreateMaxForceAttr(0.02)
                    physics = PhysxSchema.PhysxJointAPI.Apply(api.GetPrim())
                    physics.CreateArmatureAttr(0.000001)
                    physics.CreateMaxJointVelocityAttr(45)
                drives[name] = drive
            else:
                api.CreateLocalRot0Attr(Gf.Quatf(orientation))
            api.CreateLocalPos0Attr(Gf.Vec3f(matrix.ExtractTranslation()))
            api.CreateLocalPos1Attr(Gf.Vec3f(0))
        return drives, transforms

    result = {}
    for arm, position, yaw in (
        ("left", (-0.92, -0.035, 0.02), 0),
        ("right", (0.92, 0.035, 0.02), 180),
        ("assistant", (0.055, 1.04, 0.02), 270),
        ("endoscope", (0, -1.14, 0.15), 90),
    ):
        root = f"/World/Versius/{arm}"
        prim = place(
            root,
            Gf.Matrix4d()
            .SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), yaw))
            .SetTranslateOnly(Gf.Vec3d(*position)),
        )
        UsdPhysics.ArticulationRootAPI.Apply(prim)
        articulation = PhysxSchema.PhysxArticulationAPI.Apply(prim)
        articulation.CreateEnabledSelfCollisionsAttr(False)
        articulation.CreateSolverPositionIterationCountAttr(64)
        articulation.CreateSolverVelocityIterationCountAttr(4)
        drives, transforms = model(
            root, "BSU.urdf", dict(zip((f"J{i}" for i in range(1, 9)), HOME, strict=True))
        )
        tool = root + "/instrument"
        instruments = {}
        if arm == "endoscope":
            # The supplied archive has no endoscope asset. This simple shaft
            # represents its mount; the live camera moves with the TCP below.
            shaft = UsdGeom.Cylinder.Define(stage, root + "/J8_rotating_model/ScopeShaft")
            shaft.CreateRadiusAttr(0.005)
            shaft.CreateHeightAttr(0.5793)
            shaft.CreateAxisAttr("Z")
            shaft.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0.5793 / 2))
            shaft.CreateDisplayColorAttr([Gf.Vec3f(0.16, 0.19, 0.22)])
        else:
            place(tool, transforms["J8_rotating_model"])
            instruments, _ = model(
                tool,
                "fenestrated_grasper_platform.urdf"
                if arm == "assistant"
                else "needle_holder_platform.urdf",
                {},
                parent=root + "/J8_rotating_model",
                attachment=Gf.Matrix4d(1),
            )
        # Fixed TCP at the jaw pivot; leave jaw opening as an independent DOF.
        tcp = place(
            root + "/TCP",
            Gf.Matrix4d().SetTranslate(Gf.Vec3d(0, 0, 0.5793)) * transforms["J8_rotating_model"],
        )
        UsdPhysics.RigidBodyAPI.Apply(tcp)
        UsdPhysics.MassAPI.Apply(tcp).CreateMassAttr(0.001)
        mount = UsdPhysics.FixedJoint.Define(stage, root + "/joints/tcp")
        mount.CreateBody0Rel().SetTargets(
            [root + "/J8_rotating_model" if arm == "endoscope" else tool + "/yoke"]
        )
        mount.CreateBody1Rel().SetTargets([root + "/TCP"])
        mount.CreateLocalPos0Attr(Gf.Vec3f(0, 0, 0.5793 if arm == "endoscope" else 0.009))
        result[arm] = {
            "root": root,
            "drives": {"joints": {i: drives[f"J{i + 1}"] for i in range(8)}},
            "fingers": instruments,
            "limits": LIMITS,
        }
    return result
