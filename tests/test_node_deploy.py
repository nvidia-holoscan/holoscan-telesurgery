# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Redeployment applies the newly selected room, replacing the previous selection."""

import io
import tarfile
from unittest.mock import AsyncMock

import pytest
import yaml
from telesurgery.nodes.deploy import deploy


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", [None, "mira", "franka"])
async def test_deployment_includes_explicit_environment(tmp_path, monkeypatch, environment):
    class SSH:
        returncode = 0

        async def communicate(self, archive):
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                settings = tar.getmember("environment.yaml")
                assert settings.mode == 0o600
                selected = yaml.safe_load(tar.extractfile(settings))
                assert selected == {"environment": environment, "gui": False}
                assert yaml.safe_load(tar.extractfile("node.yaml"))["environment"] == environment
                assert not any(name.endswith((".so", ".pyc")) for name in tar.getnames())

    monkeypatch.setattr("asyncio.create_subprocess_exec", AsyncMock(return_value=SSH()))
    await deploy(
        "room-node", {"id": "room", "environment": environment}, 5, tmp_path / "deploy.log"
    )
