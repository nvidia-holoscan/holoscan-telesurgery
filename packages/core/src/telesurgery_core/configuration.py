# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Private, atomic YAML configuration with migration of existing JSON settings."""

import json
import os
import tempfile
from pathlib import Path

import yaml


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            yaml.safe_dump(value, stream, sort_keys=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path):
    path = Path(path)
    legacy = path.with_suffix(".json")
    if path.exists():
        try:
            value = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML configuration: {path}") from exc
    elif legacy.exists():
        value = json.loads(legacy.read_text())
        if not isinstance(value, dict):
            raise ValueError(f"Expected a mapping in {legacy}")
        save(path, value)
        legacy.unlink()
    else:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping in {path}")
    if legacy != path:
        legacy.unlink(missing_ok=True)
    return value
