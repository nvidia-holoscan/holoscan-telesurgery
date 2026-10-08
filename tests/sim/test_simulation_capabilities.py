# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Keep unsupported nodes out of simulation launch paths."""

from types import SimpleNamespace

import pytest
from telesurgery_sim.runtime import capabilities, launch


@pytest.mark.parametrize(
    "machine,gpu,supported",
    [
        ("aarch64", "NVIDIA Thor", False),
        ("aarch64", "NVIDIA RTX 6000 Ada Generation", False),
        ("aarch64", "NVIDIA GB10", True),
        ("x86_64", "NVIDIA RTX PRO 6000 Blackwell Workstation Edition", True),
        ("x86_64", "NVIDIA L40S", True),
        ("x86_64", "NVIDIA H100 80GB HBM3", False),
    ],
)
def test_simulation_platforms(monkeypatch, machine, gpu, supported):
    monkeypatch.setattr(capabilities.platform, "machine", lambda: machine)
    monkeypatch.setattr(
        capabilities.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=gpu)
    )
    capabilities.simulation_support.cache_clear()
    try:
        result = capabilities.simulation_support()
        assert result["supported"] is supported
        assert bool(result["reason"]) is not supported
    finally:
        capabilities.simulation_support.cache_clear()


@pytest.mark.asyncio
async def test_unsupported_simulation_does_not_start_docker(tmp_path, monkeypatch):
    monkeypatch.setattr(
        launch, "simulation_support", lambda: {"supported": False, "reason": "Unsupported GPU"}
    )
    simulation = launch.Simulation("mira", tmp_path)
    with pytest.raises(RuntimeError, match="Unsupported GPU"):
        await simulation.start()
    assert simulation.process is None
    assert list(tmp_path.iterdir()) == []
