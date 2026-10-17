# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA lifecycle checks use a sleeping fixture process, never a vendor API."""

import asyncio
import json
import os
import secrets
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telesurgery.nodes.registry import NodeRegistry
from telesurgery.server.application import Application
from telesurgery_robots.mira.controller import MiraController


@pytest.mark.asyncio
async def test_old_node_session_cannot_be_adopted_or_stopped(tmp_path):
    controller = MiraController({"id": "mira", "controller": {}}, tmp_path)
    info = {
        "Id": "old",
        "State": {"Running": True},
        "Config": {
            "Labels": {
                controller.label: controller.identity,
                controller.label + ".session": "previous-node",
            }
        },
    }
    controller._docker = AsyncMock(return_value=json.dumps([info]))
    assert (await controller.status())["status"] == "error"
    with pytest.raises(RuntimeError, match="another node session"):
        await controller.start()
    controller._docker.reset_mock()
    await controller.stop()
    controller._docker.assert_not_awaited()


@pytest.mark.asyncio
async def test_supervisor_terminates_vendor_fixture_when_node_lease_expires(tmp_path):
    lease = tmp_path / "lease"
    child_pid = tmp_path / "child.pid"
    lease.write_text(str(time.monotonic()))
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "telesurgery_robots.mira.supervisor",
        str(lease),
        sys.executable,
        "-c",
        "import os,sys,time; from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)",
        str(child_pid),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(3):
            while not child_pid.exists():
                await asyncio.sleep(0.01)
        lease.write_text(str(time.monotonic() - 10))
        _, error = await asyncio.wait_for(process.communicate(), 3)
        assert process.returncode == 1
        assert b"Physical stop is unconfirmed" in error
        with pytest.raises(ProcessLookupError):
            os.kill(int(child_pid.read_text()), 0)
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


@pytest.mark.asyncio
async def test_physical_device_approval_requires_confirmation_and_matches_devices(tmp_path):
    registry = NodeRegistry(SimpleNamespace(directory=tmp_path, peer_nodes={}, nodes={}))
    peer = SimpleNamespace(id="peer", writer=Mock())
    peer.writer.get_extra_info.return_value = ("127.0.0.1", 1234)
    params = {
        "name": "room",
        "token": secrets.token_urlsafe(32),
        "devices": [{"name": "MIRA", "kind": "mira", "powers_motors": True}],
    }
    key = registry.request(peer, params)["id"]
    assert registry.requests()[0]["devices"] == params["devices"]
    with pytest.raises(PermissionError, match="Confirm physical"):
        await registry.decide(key, True)
    await registry.decide(key, True, confirm_physical=True)
    registry.disconnected(peer.id)
    assert registry.request(peer, params)["status"] == "approved"
    changed = {
        **params,
        "devices": [
            *params["devices"],
            {"name": "Franka", "kind": "franka", "powers_motors": False},
        ],
    }
    assert registry.request(peer, changed)["status"] == "pending"
    # The old enrollment token cannot bypass approval of the changed devices.
    for status in ("pending", "rejected"):
        registry.pending[key]["status"] = status
        with pytest.raises(PermissionError, match="not been enrolled"):
            await Application._request(
                SimpleNamespace(node_registry=registry),
                peer,
                "node.register",
                {"id": key, "token": params["token"]},
            )
