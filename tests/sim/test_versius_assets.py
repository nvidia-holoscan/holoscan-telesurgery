# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vendor archive layouts must launch without flattening instrument mesh folders."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telesurgery_sim.environments.versius import asset_files
from telesurgery_sim.runtime.launch import Simulation


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ["flat", "nvidia-cmr/assets/URDF", "URDF", "."])
async def test_versius_launch_accepts_complete_archive_and_legacy_bundle(
    tmp_path, monkeypatch, layout
):
    workspace = tmp_path / "workspace"
    directory = workspace / "assets/versius"
    expected = {}
    for name in ("BSU.urdf", "needle_holder_platform.urdf", "fenestrated_grasper_platform.urdf"):
        folder = directory
        if layout != "flat":
            folder /= layout
            folder /= "IBSU" if name == "BSU.urdf" else "Instruments"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text('<robot name="fixture"/>')
        expected[name] = path
    if layout != "flat":
        # A previously installed flat archive must not mask a newly extracted bundle.
        (directory / "BSU.urdf").touch()
    assert asset_files(directory) == expected
    monkeypatch.setenv("TELESURGERY_WORKSPACE", str(workspace))
    monkeypatch.setattr(
        "telesurgery_sim.runtime.launch.simulation_support", lambda: {"supported": True}
    )
    launch = AsyncMock(return_value=SimpleNamespace(returncode=None))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    await Simulation("versius", tmp_path / "simulation").start()
    assert f"{directory}:/workspace/versius-assets:ro" in launch.call_args.args


def test_partial_new_archive_fails_instead_of_using_old_instruments(tmp_path):
    arm = tmp_path / "nvidia-cmr/assets/URDF/IBSU/BSU.urdf"
    arm.parent.mkdir(parents=True)
    arm.touch()
    for name in ("BSU.urdf", "needle_holder_platform.urdf", "fenestrated_grasper_platform.urdf"):
        (tmp_path / name).touch()
    with pytest.raises(FileNotFoundError, match="Instruments/needle_holder_platform.urdf"):
        asset_files(tmp_path)
