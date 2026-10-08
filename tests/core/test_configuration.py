# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Configuration writes preserve credentials and private file permissions."""

import stat

import pytest
from telesurgery_core.configuration import load, save


def test_private_yaml_and_atomic_replacement(tmp_path):
    path = tmp_path / "nodes.yaml"
    settings = {"room": {"token": "private", "port": 7448, "enabled": False}}
    assert load(path) == {}
    save(path, settings)
    assert load(path) == settings
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "enabled: false" in path.read_text()
    save(path, {})
    assert load(path) == {}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_configuration_never_overwrites_the_original(tmp_path):
    path = tmp_path / "nodes.yaml"
    path.write_text("[]")
    with pytest.raises(ValueError, match="mapping"):
        load(path)
    assert path.read_text() == "[]"
    path.write_text("token: [unterminated")
    with pytest.raises(ValueError, match="Invalid YAML"):
        load(path)
