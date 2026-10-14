# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Contact geometry for the supplied curved suture needle."""


def configure_needle_contacts(stage, root, *, mass, contact_offset):
    """Keep the curve open using short convex sections of the visible surface.

    The supplied mesh has a non-manifold seam. A single convex hull fills its
    open centre, while small convex sections preserve the curved profile and
    avoid signed-distance contacts on the defective seam. Explicit total mass
    prevents overlapping sections from counting material more than once.
    """
    import numpy as np
    import trimesh
    from pxr import PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdShade, Vt

    body = stage.GetPrimAtPath(root)
    material = UsdShade.Material.Define(stage, root + "/NeedleContactMaterial")
    physics = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(1.0)
    physics.CreateDynamicFrictionAttr(0.8)
    physics.CreateRestitutionAttr(0)
    meshes = [prim for prim in Usd.PrimRange(body) if prim.IsA(UsdGeom.Mesh)]
    for prim in meshes:
        source = UsdGeom.Mesh(prim)
        counts = np.asarray(source.GetFaceVertexCountsAttr().Get())
        if not np.all(counts == 3):
            raise ValueError("Expected a triangulated suture needle")
        points = np.asarray(source.GetPointsAttr().Get())
        faces = np.asarray(source.GetFaceVertexIndicesAttr().Get()).reshape(-1, 3)
        centers = points[faces].mean(axis=1)
        angles = np.arctan2(centers[:, 1], -centers[:, 0])
        bins = np.clip(((angles + np.pi / 2) / np.pi * 24).astype(int), 0, 23)
        prim.RemoveAPI(UsdPhysics.CollisionAPI)
        prim.RemoveAPI(UsdPhysics.MeshCollisionAPI)
        prim.RemoveAPI(PhysxSchema.PhysxSDFMeshCollisionAPI)
        contacts = UsdGeom.Xform.Define(stage, str(prim.GetPath()) + "_Contacts")
        contacts.AddTransformOp().Set(UsdGeom.Xformable(prim).GetLocalTransformation())
        contacts.CreateVisibilityAttr("invisible")
        for index in np.unique(bins):
            indices = np.unique(faces[bins == index])
            hull = trimesh.convex.convex_hull(points[indices])
            mesh = UsdGeom.Mesh.Define(stage, f"{contacts.GetPath()}/Section{index:02d}")
            mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(hull.vertices.astype(np.float32)))
            mesh.CreateFaceVertexCountsAttr([3] * len(hull.faces))
            mesh.CreateFaceVertexIndicesAttr(hull.faces.reshape(-1).tolist())
            UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
            UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr("convexHull")
            contact = PhysxSchema.PhysxCollisionAPI.Apply(mesh.GetPrim())
            contact.CreateContactOffsetAttr(contact_offset)
            contact.CreateRestOffsetAttr(0)
            UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(
                material, materialPurpose="physics"
            )
    UsdPhysics.MassAPI.Apply(body).CreateMassAttr(mass)
    rigid = PhysxSchema.PhysxRigidBodyAPI.Apply(body)
    rigid.CreateEnableCCDAttr(True)
    rigid.CreateEnableSpeculativeCCDAttr(True)
    rigid.CreateSolverPositionIterationCountAttr(32)
    rigid.CreateSolverVelocityIterationCountAttr(4)
