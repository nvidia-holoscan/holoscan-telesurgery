# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard colors carried into the native controller when it is popped out."""

import re

DEFAULTS = {
    "page": "#f5f6f7",
    "surface": "#ffffff",
    "surface-soft": "#f6f8f7",
    "ink": "#18211d",
    "muted": "#69756f",
    "border": "#e1e5e4",
    "selected": "#edf5df",
    "green-border": "#a9bd92",
    "link": "#426b09",
    "danger": "#a63735",
    "danger-border": "#eddad6",
}


def validate(appearance):
    if appearance is not None and (
        not isinstance(appearance, dict)
        or any(
            key not in DEFAULTS
            or not isinstance(value, str)
            or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
            for key, value in appearance.items()
        )
    ):
        raise ValueError("Invalid controller appearance")
    return appearance or {}


class Colors:
    def __init__(self, appearance=None):
        values = {**DEFAULTS, **validate(appearance)}
        self.mapping = {value: values[key] for key, value in DEFAULTS.items()}
        for value, key in {
            "white": "surface",
            "#a8b0ab": "muted",
            "#d5ded2": "border",
            "#cdd6cc": "border",
            "#d7dfd3": "border",
            "#eaf3df": "selected",
            "#e4f1cf": "selected",
            "#76a443": "green-border",
            "#365809": "link",
        }.items():
            self.mapping[value] = values[key]

    def __call__(self, value):
        return self.mapping.get(value, value)


DEFAULT_COLORS = Colors()


def colors(widget):
    return getattr(widget._root(), "controller_colors", DEFAULT_COLORS)
