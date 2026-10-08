# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Simulation startup must not need a camera action."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from telesurgery.server.application import Application
from telesurgery.server.http import create_app
from telesurgery_sim.runtime.launch import Simulation


@pytest.mark.asyncio
async def test_node_logs_route_to_enrolled_nodes_only(tmp_path):
    from telesurgery_core.diagnostics.logs import read_log

    path = tmp_path / "node.log"

    async def node_call(key, method, params=None):
        assert key == "room" and method in {"simulation.log", "node.log"}
        return read_log(path)

    service = SimpleNamespace(
        role="patient", node_registry=SimpleNamespace(configs={"room": {}}), node_call=node_call
    )
    app = create_app(service)
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/api/nodes/unknown/log")).status == 404
        assert (await (await client.get("/api/nodes/room/log")).json())["text"] == ""
        path.write_text("Old output\n" * 100_000 + "\n".join(f"Frame {i}" for i in range(110)))
        for suffix in ["", "?source=simulation"]:
            response = await client.get("/api/nodes/room/log" + suffix)
            assert (await response.json())["text"].splitlines() == [
                f"Frame {i}" for i in range(10, 110)
            ]
            assert response.headers["Cache-Control"] == "no-store"
        service.role = "surgeon"
        assert (await client.get("/api/nodes/room/log")).status == 404


@pytest.mark.asyncio
async def test_camera_logs_route_to_device_and_reject_unknown_or_surgeon_requests(tmp_path):
    from telesurgery.nodes.local import LocalNode

    node = LocalNode(tmp_path, None)
    node.cameras["sensor"] = {"id": "sensor"}

    async def node_call(key, method, params):
        assert key in {"host", "thor"} and method == "camera.log"
        return await node.camera_log(params["id"])

    service = SimpleNamespace(
        role="patient",
        inventory=lambda: {"cameras": [{"id": "host:sensor"}, {"id": "thor:sensor"}]},
        node_call=node_call,
    )
    app = create_app(service)
    app.cleanup_ctx.clear()
    try:
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/api/cameras/thor:unknown/log")).status == 404
            response = await client.get("/api/cameras/host:sensor/log")
            assert (await response.json())["text"] == ""
            slug = hashlib.sha256(b"sensor").hexdigest()[:12]
            (tmp_path / f"camera-{slug}.log").write_text(
                "\n".join(f"Frame {i}" for i in range(150))
            )
            response = await client.get("/api/cameras/thor:sensor/log")
            assert response.headers["Cache-Control"] == "no-store"
            assert (await response.json())["text"].splitlines() == [
                f"Frame {i}" for i in range(50, 150)
            ]
            service.role = "surgeon"
            assert (await client.get("/api/cameras/thor:sensor/log")).status == 404
            with pytest.raises(ValueError, match="unavailable"):
                await node.camera_log("../sensor")
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_environment_switch_clears_readiness_and_preserves_previous_log(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "telesurgery_sim.runtime.launch.simulation_support",
        lambda: {"supported": True, "reason": ""},
    )
    for name, content in {
        "devices.json": '{"cameras": [{"name": "Previous room"}]}',
        "progress": "Previous startup",
        "result.json": "{}",
        "simulator.log": "Previous room log",
    }.items():
        (tmp_path / name).write_text(content)
    process = SimpleNamespace(returncode=None)
    start = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    workspace = tmp_path / "custom workspace"
    monkeypatch.setenv("TELESURGERY_WORKSPACE", str(workspace))
    simulation = Simulation("franka", tmp_path)
    manifest = await simulation.start()
    assert f"{workspace}/sim-deps:/workspace/sim-deps:ro" in start.call_args.args
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
    assert not manifest.exists()


@pytest.mark.sdk
@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["mira", "franka"])
async def test_node_discovers_simulation_after_approval(
    tmp_path, monkeypatch, enrolled_node, environment
):
    monkeypatch.setattr("telesurgery.nodes.local.supported_codecs", lambda: ["h264"])

    async def launch(simulation):
        simulation.directory.mkdir(parents=True)
        return simulation.directory / "devices.json"

    monkeypatch.setattr(Simulation, "start", launch)
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    try:
        await patient.start()
        assert (await patient.status())["nodes"] == []
        node, key = await enrolled_node(patient, tmp_path / "node", environment=environment)
        initial = await patient.status()
        assert initial["nodes"][0]["simulation"]["status"] == "loading"
        assert initial["cameras"] == initial["robots"] == []
        manifest = tmp_path / "node/simulation/devices.json"
        manifest.write_text(
            json.dumps(
                {
                    "cameras": [
                        {"id": "procedure", "name": "Procedure", "kind": "Isaac Sim"},
                        {"id": "room", "name": "Room", "kind": "Isaac Sim"},
                    ],
                    "robots": [],
                }
            )
        )
        async with asyncio.timeout(5):
            while len((await patient.status())["cameras"]) != 2:
                await asyncio.sleep(0.05)
        ready = await patient.status()
        assert ready["nodes"][0]["simulation"]["status"] == "ready"
        assert {c["id"] for c in ready["cameras"]} == {f"{key}:procedure", f"{key}:room"}
        with pytest.raises(RuntimeError, match="Restart this node"):
            await patient.node_call(key, "environment.set", {"environment": "mira"})
    finally:
        await patient.close()
