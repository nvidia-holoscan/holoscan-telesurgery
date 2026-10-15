# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A measured, persistent Haply operating range shared by browser and native input."""

import json
import math
import os
from pathlib import Path

from telesurgery_core.configuration import load, save


class Range:
    def __init__(self, path=None):
        self.path = (
            path
            or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "holoscan-telesurgery"
            / "haply-range.yaml"
        )
        self.key = None
        self.bounds = None
        self.collecting = False
        self.lower = self.upper = None
        self.generation = None

    def observe(self, sample):
        if sample is None:
            self.collecting = False
            return
        if self.generation is not None and sample.generation != self.generation:
            self.collecting = False
        self.generation = sample.generation
        key = json.dumps([sample.identity[0], sample.frame])
        if key != self.key:
            self.key, self.bounds, self.collecting = key, None, False
            try:
                bounds = load(self.path).get(key)
                if bounds is not None:
                    self.validate(bounds)
                    self.bounds = bounds
            except (OSError, ValueError, TypeError):
                pass  # A damaged calibration must never enable movement.
        if self.collecting:
            self.lower = [min(a, b) for a, b in zip(self.lower, sample.position, strict=True)]
            self.upper = [max(a, b) for a, b in zip(self.upper, sample.position, strict=True)]

    @staticmethod
    def validate(bounds):
        if not isinstance(bounds, dict) or set(bounds) != {"min", "max"}:
            raise ValueError("Invalid Haply movement range")
        if any(not isinstance(v, list) or len(v) != 3 for v in bounds.values()):
            raise ValueError("Invalid Haply movement range")
        if any(
            type(v) not in (int, float) or not math.isfinite(v)
            for row in bounds.values()
            for v in row
        ):
            raise ValueError("Invalid Haply movement range")
        if any(
            not 0.04 <= hi - lo <= 1 for lo, hi in zip(bounds["min"], bounds["max"], strict=True)
        ):
            raise ValueError(
                "Sweep at least 4 cm left/right, forward/back and up/down before saving."
            )

    def action(self, action, sample):
        if action == "cancel":
            self.collecting = False
            return
        if sample is None:
            raise ValueError("Connect and calibrate Haply before setting its movement range.")
        self.observe(sample)
        if action == "start":
            self.lower = list(sample.position)
            self.upper = list(sample.position)
            self.collecting = True
        elif action == "save":
            if not self.collecting:
                raise ValueError("Start movement range calibration first.")
            bounds = {"min": self.lower, "max": self.upper}
            self.validate(bounds)
            try:
                data = load(self.path)
            except ValueError:
                data = {}
            data[self.key] = bounds
            save(self.path, data)
            self.bounds, self.collecting = bounds, False
        else:
            raise ValueError("Unknown Haply range calibration action")

    def status(self):
        return {
            "collecting": self.collecting,
            "ready": self.bounds is not None,
            "span_mm": [
                round((hi - lo) * 1000) for lo, hi in zip(self.lower, self.upper, strict=True)
            ]
            if self.collecting
            else [],
        }


def mapped_position(position, anchor, origin, bounds, workspace, basis):
    """Keep Start motionless while mapping both endpoints exactly, per axis."""
    result = []
    for i, row in enumerate(basis):
        current = sum(a * b for a, b in zip(row, position, strict=True))
        start = sum(a * b for a, b in zip(row, anchor, strict=True))
        lower = sum(a * bounds["min" if a >= 0 else "max"][j] for j, a in enumerate(row))
        upper = sum(a * bounds["max" if a >= 0 else "min"][j] for j, a in enumerate(row))
        edge = upper if current >= start else lower
        target_edge = workspace["max" if current >= start else "min"][i]
        fraction = (
            min(1, max(0, (current - start) / (edge - start))) if abs(edge - start) > 1e-6 else 0
        )
        result.append(origin[i] + fraction * (target_edge - origin[i]))
    return result
