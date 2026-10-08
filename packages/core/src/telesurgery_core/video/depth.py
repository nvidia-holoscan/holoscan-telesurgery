# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Optional, lossless color-aligned depth: float32 axial distance in metres."""

import zlib
from dataclasses import replace

import numpy as np


def attach(header, color, depth):
    if depth is None:
        return replace(header, depth_bytes=0), color
    values = np.asarray(depth, dtype="<f4")
    if values.shape != (header.height, header.width):
        raise ValueError("Depth must align with the color frame")
    packed = zlib.compress(values.tobytes(), level=1)
    return replace(header, depth_bytes=len(packed)), color + packed


def split(header, data):
    if not header.depth_bytes:
        return data, b""
    if not 0 < header.depth_bytes < len(data):
        raise ValueError("Invalid depth attachment")
    return data[: -header.depth_bytes], data[-header.depth_bytes :]


def unpack(header, packed):
    if not packed:
        return None
    size = header.width * header.height * 4
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(packed, size + 1)
    except zlib.error as exc:
        raise ValueError("Invalid depth compression") from exc
    if len(raw) != size or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ValueError("Depth dimensions do not match the frame")
    return np.frombuffer(raw, dtype="<f4").reshape(header.height, header.width)


def render(image, values, mode="color", distance=2.0, opacity=0.4):
    """Compose native RGB views on the decoder GPU; invalid depth stays transparent."""
    if mode == "color":
        return image
    import cupy as cp

    with cp.cuda.Device(image.device.id):
        if values is None:
            if mode == "overlay":
                return image
            blank = cp.zeros_like(image)
            result = cp.concatenate((image, blank), axis=1) if mode == "side" else blank
            cp.cuda.get_current_stream().synchronize()
            return result
        depth = cp.asarray(values)
        valid = cp.isfinite(depth) & (depth > 0)
        t = cp.clip(cp.where(valid, depth, 0) / distance, 0, 1)
        colors = cp.stack((255 - 215 * t, 160 - 80 * t, 20 + 190 * t), axis=-1)
        colors = cp.where(valid[..., None], colors, 0).astype(cp.uint8)
        if mode == "overlay":
            alpha = valid[..., None] * opacity
            result = (image * (1 - alpha) + colors * alpha).astype(cp.uint8)
        elif mode == "side":
            result = cp.concatenate((image, colors), axis=1)
        else:
            result = colors
        cp.cuda.get_current_stream().synchronize()
        return result
