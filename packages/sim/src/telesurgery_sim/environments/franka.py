# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ultrasound phantom contact parameters for the Franka training scene."""


def configure_phantom_contacts(stage):
    """Permit sliding contact on the phantom without altering its surface mesh.

    Compliance is per contact point: the probe produces dozens of contacts.
    These training parameters do not represent a calibrated tissue model.
    """
    from pxr import PhysxSchema, Usd, UsdPhysics, UsdShade

    material = UsdShade.Material.Define(stage, "/Telesurgery/PhantomContact")
    physics = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(0.3)
    physics.CreateDynamicFrictionAttr(0.25)
    physics.CreateRestitutionAttr(0)
    compliance = PhysxSchema.PhysxMaterialAPI.Apply(material.GetPrim())
    compliance.CreateCompliantContactStiffnessAttr(100)
    compliance.CreateCompliantContactDampingAttr(1)
    for prim in Usd.PrimRange(stage.GetPrimAtPath("/Telesurgery/AbdominalPhantom")):
        if prim.HasAPI(UsdPhysics.CollisionAPI) or prim.HasAPI(UsdPhysics.RigidBodyAPI):
            # Use an explicit physics binding; visual child materials must not
            # hide it or retain the asset's static/dynamic friction of 1000.
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, materialPurpose="physics")
