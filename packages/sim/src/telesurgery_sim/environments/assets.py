# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fetch and position a room's USD assets."""

import time
import urllib.parse
import urllib.request
from pathlib import Path


def place_static(stage, name, asset, position, rotation, scale, *, dynamic=False):
    """Place a prop without overriding transforms authored inside its asset."""
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    prop = UsdGeom.Xform.Define(stage, name)
    prop.AddTranslateOp().Set(Gf.Vec3d(*position))
    prop.AddRotateXYZOp().Set(Gf.Vec3f(*rotation))
    prop.AddScaleOp().Set(Gf.Vec3f(scale))
    reference = stage.DefinePrim(prop.GetPath().AppendChild("Asset"), "Xform")
    reference.GetReferences().AddReference(asset)
    for prim in Usd.PrimRange(reference):
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).CreateKinematicEnabledAttr(not dynamic)


def aim_camera(camera, target, offset=(0, 0, 0)):
    """Aim mounted optics in world space, preserving the mount, scale and screen up."""
    from pxr import Gf, UsdGeom

    xform = UsdGeom.Xformable(camera)
    world = xform.ComputeLocalToWorldTransform(0)
    position = world.ExtractTranslation() + Gf.Vec3d(*offset)
    view = Gf.Matrix4d().SetLookAt(
        position,
        Gf.Vec3d(*target),
        world.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized(),
    )
    transform = Gf.Transform(world)
    transform.SetTranslation(position)
    transform.SetRotation(Gf.Transform(view.GetInverse()).GetRotation())
    parent = xform.ComputeParentToWorldTransform(0)
    local = Gf.Transform(transform.GetMatrix() * parent.GetInverse())
    # Isaac's Camera wrapper removes matrix ops while normalizing transforms.
    # Author its supported TRS ops so sensor setup/resolution changes retain the aim.
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(local.GetTranslation())
    xform.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(local.GetRotation().GetQuat())
    xform.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(local.GetScale())


def fetch(url, directory):
    from pxr import Sdf, UsdUtils

    visited = set()
    base = urllib.parse.urlsplit(url)

    def download(address):
        address = urllib.parse.urljoin(url, address)
        parsed = urllib.parse.urlsplit(address)
        if parsed.scheme != "https" or parsed.netloc != base.netloc:
            raise ValueError(f"Unsupported asset origin: {address}")
        path = Path(directory, parsed.path.lstrip("/")).resolve()
        if not path.is_relative_to(Path(directory).resolve()):
            raise ValueError("Asset path escapes the simulation directory")
        if address in visited:
            return path
        visited.add(address)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            print(f"Downloading asset: {path.name}", flush=True)
            for attempt in range(3):
                try:
                    # HTTPS and same-origin validation above.
                    with urllib.request.urlopen(address, timeout=30) as response:  # nosec B310
                        temporary = path.with_suffix(path.suffix + ".download")
                        temporary.write_bytes(response.read())
                        temporary.replace(path)
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    time.sleep(1)
        if path.suffix.lower() in {".usd", ".usda", ".usdc"}:
            layer = Sdf.Layer.FindOrOpen(str(path))
            if layer is None:
                raise RuntimeError(f"Invalid USD layer: {path}")
            groups = UsdUtils.ExtractExternalReferences(str(path))
            for dependency in {item for group in groups for item in group}:
                # MDL modules without a relative prefix come from Isaac Sim.
                if dependency.endswith(".mdl") and not dependency.startswith("."):
                    continue
                download(urllib.parse.urljoin(address, dependency))
        return path

    return str(download(url))
