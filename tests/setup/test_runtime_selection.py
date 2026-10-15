# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Choose camera support before either native or container startup."""

import importlib.util
from pathlib import Path

import pytest
from telesurgery_core.configuration import save

spec = importlib.util.spec_from_file_location(
    "select_runtime", Path(__file__).resolve().parents[2] / "scripts/select_runtime.py"
)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.mark.parametrize("found,expected", [({}, "5"), ({"192.168.0.2": ["linux"]}, "4")])
def test_announcement_selects_runtime_without_installed_sdks(
    tmp_path, monkeypatch, found, expected
):
    calls = []

    def discover(timeout, *, first):
        calls.append((timeout, first))
        return found

    monkeypatch.setattr(runtime, "discover", discover)
    assert runtime.select(tmp_path, "camera") == expected
    assert calls == [(2.5, True)]


@pytest.mark.parametrize(
    "filename,document",
    [
        ("devices.yaml", {"cameras": [{"id": "endoscope", "source": "imx274"}]}),
        ("devices.yaml", {"cameras": [{"id": "endoscope", "kind": "HSB"}]}),
        ("streams.yaml", {"hsb-192.168.0.2-0": {"receiver": "fusa"}}),
    ],
)
def test_saved_hsb_selects_camera_support_even_offline(tmp_path, monkeypatch, filename, document):
    save(tmp_path / "nodes/room" / filename, document)
    monkeypatch.setattr(runtime, "discover", lambda *a, **kw: pytest.fail("No probe needed"))
    assert runtime.select(tmp_path, "room") == "4"
    assert runtime.select(tmp_path, all_nodes=True) == "4"


def test_named_node_does_not_inherit_another_nodes_saved_camera(tmp_path, monkeypatch):
    save(tmp_path / "nodes/other/devices.yaml", {"cameras": [{"source": "imx274"}]})
    save(
        tmp_path / "nodes/room/devices.yaml", {"cameras": [{"source": "synthetic", "name": "HSB"}]}
    )
    monkeypatch.setattr(runtime, "discover", lambda *a, **kw: {})
    assert runtime.select(tmp_path, "room") == "5"
    assert runtime.select(tmp_path, all_nodes=True) == "4"


def test_invalid_configuration_does_not_silently_select_wrong_runtime(tmp_path):
    save(tmp_path / "nodes/room/devices.yaml", {"cameras": {"source": "imx274"}})
    with pytest.raises(ValueError, match="cameras list"):
        runtime.select(tmp_path, "room")
