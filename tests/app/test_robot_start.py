# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Controller startup is node-local and independent of surgeon motion access."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telesurgery.nodes.service import NodeService
from telesurgery.server.application import Application
from telesurgery_robots.mira.controller import MiraController


@pytest.mark.asyncio
async def test_start_requires_patient_role_without_extra_confirmation():
    patient = object.__new__(Application)
    patient.role = "patient"
    patient.node_call = AsyncMock(return_value=True)
    await patient.action("robot.start", {"id": "remote:mira"})
    patient.node_call.assert_awaited_once_with("remote", "robot.start", {"id": "mira"})
    patient.role = "surgeon"
    patient.remote = SimpleNamespace(closed=asyncio.Event())
    with pytest.raises(PermissionError, match="surgeon"):
        await patient.action("robot.start", {"id": "remote:mira"})
    for method in ("robot.connect", "robot.disconnect", "robot.disconnect_all", "camera.stop_all"):
        with pytest.raises(PermissionError, match="surgeon"):
            await patient.action(method, {"id": "remote:mira"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action, device_action, kind",
    [
        ("camera.stop_all", "camera.stop", "cameras"),
        ("robot.disconnect_all", "robot.disconnect", "robots"),
    ],
)
async def test_room_stop_reports_partial_failures(action, device_action, kind):
    patient = object.__new__(Application)
    patient.role = "patient"
    patient.inventory = lambda: {
        "nodes": [
            {"id": "one", "name": "One", "status": "online"},
            {"id": "two", "name": "Two", "status": "online"},
            {"id": "lost", "name": "Lost node", "status": "offline"},
        ],
        kind: [
            {"id": "one:device", "name": "First", "status": "online"},
            {"id": "two:device", "name": "Second", "status": "online"},
            {"id": "lost:device", "name": "Lost", "status": "offline"},
        ],
    }
    calls = []

    async def call(method, params):
        calls.append((method, params["id"]))
        if params["id"] == "two:device":
            raise TimeoutError()
        return True

    patient.action = call
    result = await Application.action(patient, action, {})
    assert calls == [(device_action, "one:device"), (device_action, "two:device")]
    assert result["completed"] == ["one:device"]
    assert result["failed"] == [
        {"name": "Lost node", "error": "Node unreachable; action not confirmed"},
        {"name": "Second", "error": "TimeoutError"},
    ]


@pytest.mark.asyncio
async def test_node_starts_controller_without_restarting_online_robot():
    node = object.__new__(NodeService)
    node.room = None
    node.controller_lock = asyncio.Lock()
    node.controller_errors = {}
    node.set_connection = AsyncMock()
    controller = SimpleNamespace(start=AsyncMock())
    node.controller = lambda key: controller
    feedback = {"status": "offline", "stale": True}
    node.robots = SimpleNamespace(report=lambda: {"mira": feedback})
    await node.call("robot.start", {"id": "mira"})
    controller.start.assert_awaited_once()
    feedback.update(status="online", stale=False)
    await node.call("robot.start", {"id": "mira"})
    controller.start.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sdk,image",
    [
        (None, "holoscan-telesurgery:0.1.7"),
        ("5", "holoscan-telesurgery:0.1.7"),
        ("4", "holoscan-telesurgery:0.1.7-sdk4"),
    ],
)
async def test_controller_observation_never_starts_or_restarts_vendor(
    tmp_path, monkeypatch, sdk, image
):
    monkeypatch.setattr("telesurgery_robots.mira.controller.version", lambda package: "0.1.7")
    if sdk is None:
        monkeypatch.delenv("TELESURGERY_SDK", raising=False)
    else:
        monkeypatch.setenv("TELESURGERY_SDK", sdk)
    binary = tmp_path / "vendor-api"
    binary.write_text("fixture")
    binary.chmod(0o700)
    spec = {
        "id": "mira",
        "uri": "ws://127.0.0.1:8081",
        "motion_enabled": False,
        "controller": {"executable": str(binary), "pod_interface": "192.168.0.1"},
    }
    controller = MiraController(spec, tmp_path)
    calls, container = [], None

    async def docker(*args):
        nonlocal container
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([container]) if container else None
        if args[0] == "run":
            container = {
                "Id": "owned-id",
                "Config": {
                    "Labels": {
                        controller.label: controller.identity,
                        controller.label + ".session": controller.session,
                    }
                },
                "State": {"Running": True},
            }
        return ""

    controller._docker = docker
    assert (await controller.status())["status"] == "stopped"
    assert all(c[0] == "inspect" for c in calls)
    await controller.start()
    await controller.start()
    runs = [c for c in calls if c[0] == "run"]
    assert len(runs) == 1
    command = runs[0]
    assert image in command
    assert "telesurgery_robots.mira.supervisor" in command
    assert ("image", "inspect", image) in calls
    assert "127.0.0.1:8081:8081" in command
    assert "192.168.0.1:10000:10000/udp" in command
    assert command[command.index("--restart") + 1] == "no"
    assert command[command.index("--pull") + 1] == "never"
    assert "--privileged" not in command and "--nopod" not in command
    assert spec["motion_enabled"] is False
    container["Config"]["Labels"][controller.label] = "unrelated"
    with pytest.raises(RuntimeError, match="another installation"):
        await controller.start()
    assert len([c for c in calls if c[0] == "run"]) == 1
    container["Config"]["Labels"][controller.label] = controller.identity
    await controller.stop()


def test_managed_controller_rejects_public_api_binding(tmp_path):
    binary = tmp_path / "vendor-api"
    binary.touch(mode=0o700)
    controller = MiraController(
        {
            "id": "mira",
            "uri": "ws://0.0.0.0:8081",
            "controller": {"executable": str(binary), "pod_interface": "192.168.0.1"},
        },
        tmp_path,
    )
    with pytest.raises(ValueError, match="127.0.0.1"):
        controller.command()


@pytest.mark.asyncio
async def test_controller_stop_verifies_ownership_and_uses_container_id(tmp_path):
    controller = MiraController({"id": "mira", "controller": {}}, tmp_path)
    info = {
        "Id": "owned-container-id",
        "Config": {
            "Labels": {
                controller.label: controller.identity,
                controller.label + ".session": controller.session,
            }
        },
        "State": {"Running": True},
    }
    controller._docker = AsyncMock(side_effect=[json.dumps([info]), ""])
    controller.owned = True
    await controller.stop()
    controller._docker.assert_awaited_with("stop", "--time", "5", "owned-container-id")
    info["Config"]["Labels"][controller.label] = "another-installation"
    controller._docker = AsyncMock(return_value=json.dumps([info]))
    controller.owned = True
    with pytest.raises(RuntimeError, match="another installation"):
        await controller.stop()
    controller._docker.assert_awaited_once_with("inspect", controller.name)
    controller._docker = AsyncMock(return_value=None)
    controller.owned = True
    await controller.stop()
    controller._docker.assert_awaited_once_with("inspect", controller.name)


@pytest.mark.asyncio
async def test_node_shutdown_closes_connections_before_owned_controllers_even_on_failure():
    node = object.__new__(NodeService)
    events = []
    node.camera_starts = {}

    def disconnect():
        events.append("connections")

    async def cameras():
        events.append("cameras")
        raise RuntimeError("camera failed")

    async def controller():
        events.append("controller")

    async def simulation():
        events.append("simulation")

    node.robots = SimpleNamespace(devices={"mira": {}}, close=Mock(side_effect=disconnect))
    node.local = SimpleNamespace(robots={"mira": {}, "external": {}}, close=cameras)
    managed = SimpleNamespace(stop=controller)
    node.controllers = {"mira": managed}
    node.controller_errors = {}
    node.room = SimpleNamespace(task=None, close=simulation)
    with pytest.raises(RuntimeError, match="camera failed"):
        await node.close()
    assert events == ["connections", "cameras", "controller", "simulation"]
