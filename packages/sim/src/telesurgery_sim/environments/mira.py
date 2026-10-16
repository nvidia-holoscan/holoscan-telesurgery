# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Include MIRA's tool rolls in the arm articulation and measured feedback."""

from telesurgery_robots.mira.poses import MIRA_ROLL_LIMIT


def configure_tool_contacts(stage, root):
    """Build closed contacts from the visible jaw surfaces."""
    import numpy as np
    from pxr import PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdShade, Vt

    roots = {}
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh) or not prim.HasAPI(UsdPhysics.CollisionAPI):
            continue
        if prim.GetAttribute("physics:approximation").Get() != "sdf" or not str(
            prim.GetPath()
        ).startswith(root + "/"):
            continue
        roots[str(prim.GetParent().GetPath())] = prim.GetParent()
    material = UsdShade.Material.Define(stage, "/Telesurgery/GrasperPhysics")
    m = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    m.CreateStaticFrictionAttr(1.0)
    m.CreateDynamicFrictionAttr(0.8)
    m.CreateRestitutionAttr(0)
    for root in roots.values():
        visible = []
        for prim in Usd.PrimRange(root):
            if not prim.IsA(UsdGeom.Mesh):
                continue
            if UsdGeom.Imageable(prim).ComputeVisibility() != "invisible":
                visible.append(prim)
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                prim.RemoveAPI(UsdPhysics.CollisionAPI)
                prim.RemoveAPI(UsdPhysics.MeshCollisionAPI)
                prim.RemoveAPI(PhysxSchema.PhysxSDFMeshCollisionAPI)
        if len(visible) != 1:
            raise RuntimeError(f"Expected one visible jaw mesh: {root.GetPath()}")
        prim = visible[0]
        source = UsdGeom.Mesh(prim)
        points = np.asarray(source.GetPointsAttr().Get())
        _, keep, inverse = np.unique(
            np.round(points, 8), axis=0, return_index=True, return_inverse=True
        )
        points = points[keep]
        indices = inverse[np.array(source.GetFaceVertexIndicesAttr().Get())]
        faces = []
        offset = 0
        for count in source.GetFaceVertexCountsAttr().Get():
            row = indices[offset : offset + count]
            faces.extend([[row[0], row[i], row[i + 1]] for i in range(1, count - 1)])
            offset += count
        faces = np.array(faces)
        faces = faces[np.all(np.diff(np.sort(faces, axis=1), axis=1) != 0, axis=1)]
        _, keep = np.unique(np.sort(faces, axis=1), axis=0, return_index=True)
        faces = faces[keep]
        areas = np.linalg.norm(
            np.cross(
                points[faces[:, 1]] - points[faces[:, 0]], points[faces[:, 2]] - points[faces[:, 0]]
            ),
            axis=1,
        )
        edges = np.sort(faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
        _, inv, counts = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
        dangling = ((counts[inv].reshape(-1, 3) == 1).sum(axis=1) >= 2) & (areas < 1e-6)
        faces = faces[~dangling]
        edges = np.sort(faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        if not np.all(counts == 2):
            raise RuntimeError(f"MIRA jaw surface is not closed: {prim.GetPath()}")
        mesh = UsdGeom.Mesh.Define(stage, str(prim.GetPath()) + "_Contact")
        mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points.astype(np.float32)))
        mesh.CreateFaceVertexCountsAttr([3] * len(faces))
        mesh.CreateFaceVertexIndicesAttr(faces.reshape(-1).tolist())
        mesh.CreateVisibilityAttr("invisible")
        # Mesh prims have no own transform in this asset.
        if UsdGeom.Xformable(prim).GetOrderedXformOps():
            raise RuntimeError(f"Unexpected jaw mesh transform: {prim.GetPath()}")
        UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr("sdf")
        PhysxSchema.PhysxSDFMeshCollisionAPI.Apply(mesh.GetPrim()).CreateSdfResolutionAttr(512)
        contact = PhysxSchema.PhysxCollisionAPI.Apply(mesh.GetPrim())
        contact.CreateContactOffsetAttr(0.03)
        contact.CreateRestOffsetAttr(0)
        # Finite contact across the jaw teeth resists needle spin (cm units).
        contact.CreateTorsionalPatchRadiusAttr(0.2)
        contact.CreateMinTorsionalPatchRadiusAttr(0.15)
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material, materialPurpose="physics")


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


def configure_task_physics(stage):
    """Bound tool drives and small-object contacts in the centimetre MIRA asset.

    These are simulation parameters, not physical MIRA hardware ratings.
    Jaw torque is 0.3 N m; angular USD force-drive gains are per degree.
    """
    import re

    from pxr import PhysxSchema, Usd, UsdPhysics, UsdShade
    from telesurgery_robots.mira.velocity import SIMULATION
    from telesurgery_sim.environments.needle import configure_needle_contacts

    configure_needle_contacts(
        stage, "/Telesurgery/SutureNeedle/Asset", mass=0.012, contact_offset=0.01
    )

    # Damped acceleration drives with explicit torque and speed limits.
    for prim in stage.Traverse():
        match = re.fullmatch(r"([LR])J([1-6])(?:_1)?_joint", prim.GetName())
        if not match or not prim.HasAPI(UsdPhysics.DriveAPI, "angular"):
            continue
        index = int(match[2]) - 1
        drive = UsdPhysics.DriveAPI.Get(prim, "angular")
        drive.CreateTypeAttr("acceleration" if index < 5 else "force")
        drive.CreateStiffnessAttr(6400 if index < 5 else 5236)
        drive.CreateDampingAttr(160 if index < 5 else 34.9)
        drive.CreateMaxForceAttr(10_000_000 if index < 4 else 30_000 if index == 4 else 3000)
        PhysxSchema.PhysxJointAPI.Apply(prim).CreateMaxJointVelocityAttr(
            SIMULATION["arm_deg_s"] if index < 4 else SIMULATION["roll_deg_s"] if index == 4 else 20
        )
        if match[1] == "L" and index == 5:
            UsdPhysics.RevoluteJoint(prim).CreateLowerLimitAttr(0)

    # Compliant rubber contact; this changes contact forces, not geometry or attachment.
    material = UsdShade.Material.Define(stage, "/Telesurgery/PadPhysics")
    pad_material = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    pad_material.CreateStaticFrictionAttr(0.7)
    pad_material.CreateDynamicFrictionAttr(0.6)
    pad_material.CreateRestitutionAttr(0)
    soft = PhysxSchema.PhysxMaterialAPI.Apply(material.GetPrim())
    soft.CreateCompliantContactStiffnessAttr(1500)
    soft.CreateCompliantContactDampingAttr(10)
    for prim in Usd.PrimRange(stage.GetPrimAtPath("/Telesurgery/SuturePad")):
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, materialPurpose="physics")

    # The tool's collision approximation overlaps its own forearm housing.
    for arm in "LR":
        adjacent = [
            p.GetPath()
            for p in stage.Traverse()
            if p.HasAPI(UsdPhysics.RigidBodyAPI)
            and p.GetName() in (arm + "J4", arm + "J5", arm + "J6", arm + "J6_001")
        ]
        for path in adjacent:
            if "J6" not in path.name:
                continue
            UsdPhysics.FilteredPairsAPI.Apply(
                stage.GetPrimAtPath(path)
            ).CreateFilteredPairsRel().SetTargets([p for p in adjacent if p != path])
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            api = PhysxSchema.PhysxArticulationAPI.Apply(prim)
            api.CreateSolverPositionIterationCountAttr(32)
            api.CreateSolverVelocityIterationCountAttr(4)
