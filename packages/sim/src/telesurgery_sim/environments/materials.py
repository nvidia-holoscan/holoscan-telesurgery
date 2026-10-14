# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Preserve the supplied GLB casework, metal finishes and logo textures in USD."""

import hashlib
import io
import json

import numpy as np


def bind_mesh_material(stage, surface, mesh, cache, fallback):
    from pxr import Gf, Sdf, UsdGeom, UsdShade, Vt

    source = getattr(mesh.visual, "material", None)
    color = getattr(source, "baseColorFactor", None)
    color = list(np.asarray(color, float) / 255) if color is not None else [1.0] * 4
    if source is None:
        color = fallback
    metallic = getattr(source, "metallicFactor", None)
    roughness = getattr(source, "roughnessFactor", None)
    texture = getattr(source, "baseColorTexture", None)
    uv = getattr(mesh.visual, "uv", None)
    image_path = None
    if texture is not None and uv is not None:
        encoded = io.BytesIO()
        texture.save(encoded, format="PNG")
        data = encoded.getvalue()
        cache.mkdir(parents=True, exist_ok=True)
        image_path = cache / (hashlib.sha256(data).hexdigest() + ".png")
        if not image_path.exists():
            image_path.write_bytes(data)
        UsdGeom.PrimvarsAPI(surface).CreatePrimvar(
            "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.vertex
        ).Set(Vt.Vec2fArray.FromNumpy(np.asarray(uv, np.float32)))
    alpha_mode = getattr(source, "alphaMode", None) or "OPAQUE"
    cutoff = getattr(source, "alphaCutoff", None)
    values = {
        "color": color,
        "metallic": metallic if metallic is not None else 1.0 if source else 0.0,
        "roughness": roughness if roughness is not None else 1.0,
        "texture": str(image_path) if image_path else None,
        "alpha_mode": alpha_mode,
        "cutoff": cutoff if cutoff is not None else 0.5,
    }
    key = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]
    path = "/World/Looks/Versius/Material_" + key
    material = UsdShade.Material.Get(stage, path)
    if not material:
        material = UsdShade.Material.Define(stage, path)
        shader = UsdShade.Shader.Define(stage, path + "/Surface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color[:3]))
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(values["metallic"])
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(values["roughness"])
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        if alpha_mode != "OPAQUE":
            shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(color[3])
        if alpha_mode == "MASK":
            shader.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(values["cutoff"])
        if image_path:
            reader = UsdShade.Shader.Define(stage, path + "/UV")
            reader.CreateIdAttr("UsdPrimvarReader_float2")
            reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
            reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)
            image = UsdShade.Shader.Define(stage, path + "/Texture")
            image.CreateIdAttr("UsdUVTexture")
            image.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(image_path)))
            image.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
            image.CreateInput("scale", Sdf.ValueTypeNames.Float4).Set(Gf.Vec4f(*color))
            image.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
                reader.ConnectableAPI(), "result"
            )
            image.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
            image.CreateOutput("a", Sdf.ValueTypeNames.Float)
            shader.GetInput("diffuseColor").ConnectToSource(image.ConnectableAPI(), "rgb")
            if alpha_mode != "OPAQUE":
                shader.GetInput("opacity").ConnectToSource(image.ConnectableAPI(), "a")
    surface.CreateDisplayColorAttr([Gf.Vec3f(*color[:3])])
    surface.CreateDoubleSidedAttr(bool(getattr(source, "doubleSided", False)))
    UsdShade.MaterialBindingAPI.Apply(surface.GetPrim()).Bind(material)
