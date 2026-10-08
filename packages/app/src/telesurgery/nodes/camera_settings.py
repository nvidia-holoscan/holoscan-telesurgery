# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate capture choices against a camera's advertised modes."""

from telesurgery_core.video.config import Config

DEFAULTS = {
    key: getattr(Config, key)
    for key in (
        "width",
        "height",
        "fps",
        "pixel_format",
        "codec",
        "qp",
        "jpeg_quality",
        "encoder_preset",
        "receiver",
        "depth",
    )
}


def modes(camera):
    if "modes" in camera:
        return camera["modes"]
    if camera.get("source") == "imx274":
        # Both adapters implement IMX274 RAW10 modes 0 and 1.
        return [{"width": w, "height": h, "fps": [60]} for w, h in ((1920, 1080), (3840, 2160))]
    return [
        {
            "width": camera.get("width", Config.width),
            "height": camera.get("height", Config.height),
            "fps": [camera.get("fps", Config.fps)],
            "pixel_format": camera.get("pixel_format", ""),
        }
    ]


def select(camera, settings=None):
    if settings is not None and (
        not isinstance(settings, dict) or settings.keys() - DEFAULTS.keys()
    ):
        raise ValueError("Unknown stream setting")
    defaults = {key: camera.get(key, value) for key, value in DEFAULTS.items()}
    selected = {**defaults}
    selected.update(settings or {})
    if type(selected["depth"]) is not bool:
        raise ValueError("Depth must be enabled or disabled")
    if selected["depth"] and not camera.get("depth_supported"):
        raise ValueError("This camera does not provide depth")
    if selected["depth"] and selected["fps"] not in camera.get("depth_fps", [selected["fps"]]):
        raise ValueError("Depth is unavailable at this frame rate")
    if camera.get("source") == "imx274":
        receivers = camera.get("receivers", ["linux"])
        if selected["receiver"] == "auto":
            selected["receiver"] = receivers[0]
        if selected["receiver"] not in receivers:
            raise ValueError("This camera does not support the selected HSB receiver")
    elif selected["receiver"] != "auto":
        raise ValueError("Receiver selection is only available for HSB cameras")
    if selected["codec"] not in camera.get("codecs", ["h264", "h265", "nvjpeg", "raw-bgr8"]):
        raise ValueError("This node does not support the selected codec")
    if type(selected["qp"]) is not int or not 0 <= selected["qp"] <= 51:
        raise ValueError("Quality (QP) must be an integer from 0 to 51")
    if selected["encoder_preset"] not in ("P1", "P3", "P5"):
        raise ValueError("Choose a supported encoder speed")
    if type(selected["jpeg_quality"]) is not int or not 1 <= selected["jpeg_quality"] <= 100:
        raise ValueError("JPEG quality must be an integer from 1 to 100")
    for mode in modes(camera):
        if (
            all(selected[key] == mode.get(key, "") for key in ("width", "height", "pixel_format"))
            and selected["fps"] in mode["fps"]
        ):
            return selected
    # Devices without enumeration can still use their configured defaults.
    if not modes(camera) and all(
        selected[k] == defaults[k] for k in ("width", "height", "fps", "pixel_format")
    ):
        return selected
    raise ValueError("This camera does not support that resolution, frame rate and capture format")
