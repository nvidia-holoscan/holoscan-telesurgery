# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Display-only crop metadata. Slicing retains the decoded GPU allocation."""

import math


def settings(scale=1.0, x=0.5, y=0.5):
    if (
        not all(type(v) in (int, float) and math.isfinite(v) for v in (scale, x, y))
        or not 1 <= scale <= 4
        or not 0 <= x <= 1
        or not 0 <= y <= 1
    ):
        raise ValueError("Invalid view zoom settings")
    return {"scale": float(scale), "x": float(x), "y": float(y)}


def crop(image, scale=1.0, x=0.5, y=0.5):
    if scale == 1:
        return image
    height, width = image.shape[:2]
    w, h = max(1, round(width / scale)), max(1, round(height / scale))
    # x/y select the center in original-image coordinates, bounded at the edges.
    left = max(0, min(width - w, round(x * width - w / 2)))
    top = max(0, min(height - h, round(y * height - h / 2)))
    return image[top : top + h, left : left + w]
