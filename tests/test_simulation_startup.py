# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Simulation startup must not need a camera action."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from telesurgery.server.application import Application
from telesurgery.server.http import create_app
from telesurgery_sim.launch import Simulation


@pytest.mark.asyncio
async def test_simulator_log_returns_recent_output_and_handles_missing_file(tmp_path):
    simulation = Simulation("mira", tmp_path)
    service = SimpleNamespace(
        simulation=simulation, role="patient", start=AsyncMock(), close=AsyncMock()
    )
    app = create_app(service)
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/api/simulation/log")
        assert response.status == 200
        assert (await response.json())["text"] == ""
        path = tmp_path / "simulator.log"
        path.write_text("Old output\n" * 100_000 + "\n".join(f"Frame {i}" for i in range(110)))
        response = await client.get("/api/simulation/log")
        log = await response.json()
        assert log["text"].splitlines() == [f"Frame {i}" for i in range(10, 110)]
        assert log["path"] == str(path)
        assert log["updated_seconds_ago"] < 5
        assert response.headers["Cache-Control"] == "no-store"
        path.write_text("New startup output")
        assert (await (await client.get("/api/simulation/log")).json())[
            "text"
        ] == "New startup output"
        service.simulation = None
        assert (await client.get("/api/simulation/log")).status == 404


@pytest.mark.asyncio
async def test_node_logs_are_bounded_and_only_available_for_enrolled_patient_nodes(tmp_path):
    service = SimpleNamespace(
        role="patient", directory=tmp_path, node_registry=SimpleNamespace(configs={"thor": {}})
    )
    app = create_app(service)
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/api/nodes/unknown/log")).status == 404
        response = await client.get("/api/nodes/thor/log")
        assert (await response.json())["text"] == ""
        (tmp_path / "deploy-thor.log").write_text(
            "Old output\n" * 100_000 + "\n".join(f"Step {i}" for i in range(110))
        )
        response = await client.get("/api/nodes/thor/log")
        log = await response.json()
        assert log["text"].splitlines() == [f"Step {i}" for i in range(10, 110)]
        assert response.headers["Cache-Control"] == "no-store"
        service.role = "surgeon"
        assert (await client.get("/api/nodes/thor/log")).status == 404


@pytest.mark.asyncio
async def test_environment_switch_clears_readiness_and_preserves_previous_log(
    tmp_path, monkeypatch
):
    for name, content in {
        "devices.json": '{"cameras": [{"name": "Previous room"}]}',
        "progress": "Previous startup",
        "result.json": "{}",
        "simulator.log": "Previous room log",
    }.items():
        (tmp_path / name).write_text(content)
    process = SimpleNamespace(returncode=None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    simulation = Simulation("franka", tmp_path)
    manifest = await simulation.start()
    assert not manifest.exists()
    assert not (tmp_path / "result.json").exists()
    assert (tmp_path / "simulator.previous.log").read_text() == "Previous room log"
    assert simulation.status()["stage"] == "Starting Isaac Sim"
    assert simulation.status()["cameras"] == ["Franka wrist camera", "Franka room camera"]
    (tmp_path / "progress").write_text("Warming up camera rendering")
    assert simulation.status()["stage"] == "Warming up camera rendering"
    manifest.write_text("{}")
    assert simulation.status()["status"] == "ready"
    (tmp_path / "simulator.log").write_text("Camera initialization failed")
    process.returncode = 1
    assert simulation.status() == {"status": "error", "error": "Camera initialization failed"}


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_patient_discovers_delayed_simulation_manifest_without_actions(tmp_path, monkeypatch):
    monkeypatch.setattr("telesurgery.nodes.local.supported_codecs", lambda: ["h264"])

    async def launch(simulation):
        simulation.directory.mkdir(parents=True)
        return simulation.directory / "devices.json"

    monkeypatch.setattr(Simulation, "start", launch)
    patient = Application("patient", tmp_path, endpoint_port=0, environment="mira")
    try:
        await patient.start()
        initial = await patient.status()
        assert initial["simulation"]["status"] == "loading"
        assert initial["cameras"] == initial["robots"] == []
        (tmp_path / "simulation" / "devices.json").write_text(
            json.dumps(
                {
                    "cameras": [
                        {"id": "procedure", "name": "MIRA procedure camera", "kind": "Isaac Sim"},
                        {"id": "room", "name": "MIRA room camera", "kind": "Isaac Sim"},
                    ],
                    "robots": [{"id": "mira", "name": "MIRA", "kind": "mira-sim"}],
                }
            )
        )
        async with asyncio.timeout(5):
            while len((await patient.status())["cameras"]) != 2:
                await asyncio.sleep(0.1)
        ready = await patient.status()
        assert ready["simulation"]["status"] == "ready"
        assert {camera["status"] for camera in ready["cameras"]} == {"stopped"}
        assert ready["robots"][0]["id"] == "host:mira"
    finally:
        await patient.close()


@pytest.fixture
def simulated_rooms(monkeypatch):
    closed = []

    async def launch(simulation):
        simulation.directory.mkdir(parents=True, exist_ok=True)
        manifest = simulation.directory / "devices.json"
        manifest.unlink(missing_ok=True)
        return manifest

    async def stop(simulation):
        closed.append(simulation.environment)

    monkeypatch.setattr(Simulation, "start", launch)
    monkeypatch.setattr(Simulation, "close", stop)
    monkeypatch.setattr("telesurgery.nodes.local.camera_devices", lambda: [])
    monkeypatch.setattr("telesurgery.nodes.local.supported_codecs", lambda: ["h264"])
    return closed


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_managed_environment_switch_and_restart(tmp_path, simulated_rooms):
    from telesurgery.nodes.service import NodeService

    node = NodeService(tmp_path, AsyncMock(), managed=True)

    async def settle():
        await asyncio.wait_for(asyncio.shield(node.room.task), 5)
        assert not node.room.error

    try:
        await node.start("mira")
        await settle()
        assert (await node.call("inventory"))["simulation"]["status"] == "loading"
        await node.call("environment.set", {"environment": "franka"})
        await settle()
        assert simulated_rooms == ["mira"]
        manifest = tmp_path / "simulation/devices.json"
        manifest.write_text(json.dumps({"cameras": [], "robots": []}))
        assert (await node.call("inventory"))["simulation"]["status"] == "ready"
        (manifest.parent / "simulator.log").write_text("Franka ready")
        assert (await node.call("simulation.log"))["text"] == "Franka ready"
        node.local.workers["active"] = {}
        with pytest.raises(ValueError, match="Stop the node's streams"):
            await node.call("environment.set", {"environment": None})
        node.local.workers.clear()
        await node.close()
        node = NodeService(tmp_path, AsyncMock(), managed=True)
        await node.start()
        await settle()
        assert (await node.call("inventory"))["environment"] == "franka"
        await node.call("environment.set", {"environment": None})
        await settle()
        await node.close()
        node = NodeService(tmp_path, AsyncMock(), managed=True)
        await node.start()
        await settle()
        assert (await node.call("inventory"))["simulation"] is None
        assert node.local.simulation is None
    finally:
        node.local.workers.pop("active", None)
        await node.close()


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_manual_node_environment_follows_restart_arguments(tmp_path, simulated_rooms):
    from telesurgery.nodes.standalone import NodeServer

    node = NodeServer(tmp_path / "node", 0)
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    try:
        await node.start("mira")
        await patient.start()
        result = await patient.action(
            "node.connect",
            {"address": f"127.0.0.1:{node.port}", "code": node.pairing_code},
        )
        key, port = result["id"], node.port
        assert (await patient.node_call(key, "inventory"))["environment"] == "mira"
        with pytest.raises(ValueError, match="SSH-managed"):
            await patient.action("node.environment", {"id": key, "environment": "franka"})
        with pytest.raises(RuntimeError, match="Restart this node"):
            await patient.node_call(key, "environment.set", {"environment": "franka"})
        for environment in ("franka", None):
            await node.close()
            node = NodeServer(tmp_path / "node", port)
            await node.start(environment)
            async with asyncio.timeout(15):
                while patient.nodes[key].get("environment") != environment:
                    await asyncio.sleep(0.1)
            assert (await patient.node_call(key, "inventory"))["environment"] == environment
        assert not (tmp_path / "node/environment.yaml").exists()
    finally:
        await patient.close()
        await node.close()
