# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A surgeon-drawn priority area: picture quality is concentrated inside it.

The area is one polygon in picture coordinates (0-1, x right, y down), so it is
independent of resolution. The encoder receives it as a coarse grid of cells; no
pixels are modified and the stream decodes like any other.

The node keeps the area in memory and hands it to a camera's worker through a file
beside that worker's settings; the worker reports what its encoder accepted in a
second file. Each write replaces the file, so a reader sees a whole document.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np
from telesurgery_core.video.encoder_settings import parse_extra

# Cells the encoder bridge expects: rows x columns, 1 inside the area.
GRID_ROWS, GRID_COLUMNS = 160, 285
MIN_POINTS, MAX_POINTS = 3, 64
MIN_COVERAGE = 0.005  # share of the picture; smaller areas are slips of the pen
VIDEO_CODECS = ("h264", "h265")
REQUEST_SUFFIX = ".region"  # node -> worker: {"revision": int, "points": [[x, y], ...] | null}
STATUS_SUFFIX = ".region-status"  # worker -> node: {"supported", "blocked", "revision", "error"}


def mask(points, rows=GRID_ROWS, columns=GRID_COLUMNS):
    """Cells whose centre lies inside the polygon, as C-contiguous uint8 (rows, columns).

    A cell is inside when the polygon winds around its centre, so a lasso that
    crosses itself still fills everything it encloses.
    """
    polygon = np.asarray(points, dtype=np.float64)
    x = (np.arange(columns) + 0.5) / columns
    y = (np.arange(rows) + 0.5) / rows
    winding = np.zeros((rows, columns), dtype=np.int32)
    for (x0, y0), (x1, y1) in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        if y0 == y1:
            continue
        crossed = (y >= min(y0, y1)) & (y < max(y0, y1))
        if not crossed.any():
            continue
        edge = x0 + (y[crossed] - y0) * (x1 - x0) / (y1 - y0)
        winding[crossed] += (1 if y1 > y0 else -1) * (x[None, :] < edge[:, None])
    return np.ascontiguousarray(winding != 0, dtype=np.uint8)


# The dashboard's outline colours (view-region.css), as RGB for the native viewer.
OUTLINE_LINE = (183, 239, 102)
OUTLINE_HALO = (12, 18, 15)


def _band(columns, rows, thickness, width, height):
    """Flat indices of the pixels within a square pen of this thickness around each sample."""
    reach = np.arange(thickness) - thickness // 2
    x = (columns[:, None] + reach[None, :]).clip(0, width - 1)
    y = (rows[:, None] + reach[None, :]).clip(0, height - 1)
    return np.unique(y[:, :, None] * width + x[:, None, :]).astype(np.int32)


def outline(points, width, height):
    """Pixels of the area's outline in a width x height picture: (halo, line).

    Both are sorted flat indices (row * width + column) for the native viewer, which
    has no overlay layer and paints them into each frame. The line is about 2 pixels
    per 1080 picture lines and the dark halo around it keeps it visible on any content,
    as on the dashboard.
    """
    polygon = np.asarray(points, dtype=np.float64) * (width, height)
    columns, rows = [], []
    for (x0, y0), (x1, y1) in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        steps = max(2, int(np.ceil(max(abs(x1 - x0), abs(y1 - y0)) * 2)) + 1)
        along = np.linspace(0.0, 1.0, steps)
        columns.append(x0 + (x1 - x0) * along)
        rows.append(y0 + (y1 - y0) * along)
    columns = np.floor(np.concatenate(columns)).astype(np.int64).clip(0, width - 1)
    rows = np.floor(np.concatenate(rows)).astype(np.int64).clip(0, height - 1)
    # Each pixel of the path once, however many samples fell in it.
    path = np.unique(rows * width + columns)
    rows, columns = path // width, path % width
    line = max(2, round(height / 540))
    halo = line + 2 * max(1, round(height / 1080))
    return _band(columns, rows, halo, width, height), _band(columns, rows, line, width, height)


def validate(points):
    """Return the polygon as [[x, y], ...] or raise ValueError with a message for the user."""
    if not isinstance(points, (list, tuple)) or not MIN_POINTS <= len(points) <= MAX_POINTS:
        raise ValueError(f"A priority area needs {MIN_POINTS} to {MAX_POINTS} points")
    polygon = []
    for point in points:
        if (
            not isinstance(point, (list, tuple))
            or len(point) != 2
            or any(type(value) not in (int, float) for value in point)
            or not all(math.isfinite(value) and 0 <= value <= 1 for value in point)
        ):
            raise ValueError("Priority area points must lie inside the picture")
        polygon.append([round(float(point[0]), 4), round(float(point[1]), 4)])
    if mask(polygon).mean() < MIN_COVERAGE:
        raise ValueError("Draw a larger priority area")
    return polygon


def unavailable(codec, encoder_extra=""):
    """Why a stream's settings rule out a priority area; empty when they allow one."""
    if codec not in VIDEO_CODECS:
        return "it needs an H.264 or H.265 stream"
    try:
        extra = parse_extra(encoder_extra)
    except ValueError:
        return ""
    if "aq" in extra or extra.get("temporalaq"):
        # NVIDIA's region path requires the encoder's own adaptive quantization off.
        return "turn off adaptive quantization (aq, temporalaq) in the stream's advanced settings"
    return ""


def _write(path, document):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(document, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(path):
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def stamp(path):
    """Identity of the file's current contents; every replacement changes it."""
    try:
        status = os.stat(path)
    except OSError:
        return None
    return status.st_ino, status.st_mtime_ns, status.st_size


def write_request(path, revision, points):
    _write(path, {"revision": revision, "points": points})


def read_request(path):
    """(revision, points or None) for the worker; a missing or damaged file means no area."""
    document = _read(path)
    points = document.get("points")
    try:
        points = validate(points) if points is not None else None
    except ValueError:
        points = None
    return document.get("revision"), points


def write_status(path, supported, blocked, revision, error=""):
    """What the worker's current encoder did with the request numbered `revision`.

    supported: the encoder can take an area now. blocked: the stream setting that rules
    one out (see unavailable), so the node can tell that apart from an encoder that
    lacks the capability.
    """
    _write(
        path,
        {"supported": bool(supported), "blocked": blocked, "revision": revision, "error": error},
    )


def read_status(path):
    return _read(path)
