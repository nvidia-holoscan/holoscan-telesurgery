# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Saved configuration migrates without losing credentials or granting file access."""

import json
import stat

import pytest
from telesurgery_core.configuration import load, save


def test_private_yaml_migration_and_atomic_replacement(tmp_path):
    path = tmp_path / "nodes.yaml"
    previous = path.with_suffix(".json")
    settings = {"room": {"token": "private", "port": 7448, "enabled": False}}
    previous.write_text(json.dumps(settings))
    assert load(path) == settings
    assert not previous.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "enabled: false" in path.read_text()
    save(path, {})
    assert load(path) == {}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_configuration_never_overwrites_the_original(tmp_path):
    path = tmp_path / "nodes.yaml"
    previous = path.with_suffix(".json")
    previous.write_text("[]")
    with pytest.raises(ValueError, match="mapping"):
        load(path)
    assert previous.read_text() == "[]" and not path.exists()
    path.write_text("token: [unterminated")
    with pytest.raises(ValueError, match="Invalid YAML"):
        load(path)
