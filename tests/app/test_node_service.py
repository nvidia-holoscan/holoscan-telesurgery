# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Nodes require patient approval and serve video directly after admission."""

import asyncio
import json
import secrets
import stat
from dataclasses import asdict

import pytest
from telesurgery.nodes.address import endpoint
from telesurgery_core.configuration import load


def test_patient_addresses():
    assert endpoint("room-node") == ("room-node", 7447, "room-node:7447")
    assert endpoint(" patient-host ", 7447) == ("patient-host", 7447, "patient-host:7447")
    assert endpoint("patient-host:7555", 7447) == ("patient-host", 7555, "patient-host:7555")
    assert endpoint("[::1]:7555") == ("::1", 7555, "[::1]:7555")
    for address in ("", "host:0", "host:65536", "http://host", "user@host", "host/path"):
        with pytest.raises(ValueError):
            endpoint(address)


@pytest.mark.parametrize(
    "name",
    [
        "spark-4129-franka",
        "Training room",
    ],
)
def test_simulation_node_names_preserve_explicit_names(tmp_path, name):
    from telesurgery.server.application import Application

    patient = Application("patient", tmp_path)
    patient.nodes["spark"] = {"name": name, "environment": "franka"}
    assert patient.inventory()["nodes"][0]["name"] == name


async def until(predicate):
    async with asyncio.timeout(25):
        while not predicate():
            await asyncio.sleep(0.05)


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_node_admission_identity_rejection_and_restart(tmp_path, monkeypatch):
    from telesurgery.nodes.client import NodeClient
    from telesurgery.server.application import Application

    discoveries = []

    def discover(*args):
        discoveries.append(args)
        return [], []

    monkeypatch.setattr("telesurgery.nodes.local.discover", discover)
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    tasks = []
    try:
        await patient.start()
        assert patient.inventory() == {"nodes": [], "cameras": [], "robots": []}
        assert not discoveries
        nodes = [
            NodeClient(
                tmp_path / str(i),
                {
                    "host": "127.0.0.1",
                    "port": patient.endpoint_port,
                    "name": "Same name",
                    "token": secrets.token_urlsafe(32),
                    "video_port": 0,
                },
            )
            for i in range(2)
        ]
        tasks = [asyncio.create_task(node.run()) for node in nodes]
        await until(lambda: len(patient.node_registry.requests()) == 2)
        assert not discoveries and all(not node.started for node in nodes)
        public = json.dumps(await patient.status())
        assert all(node.config["token"] not in public for node in nodes)
        for request in patient.node_registry.pending.values():
            peer = patient.peers[request["peer"]]["peer"]
            with pytest.raises(RuntimeError, match="approval"):
                await peer.call("camera.start", {"id": "camera"})
        keys = {item["token"]: key for key, item in patient.node_registry.pending.items()}
        one, two = [keys[node.config["token"]] for node in nodes]
        assert one != two  # A display name does not identify a node.
        await patient.action("node.approve", {"id": one})
        await patient.action("node.reject", {"id": two})
        await until(lambda: nodes[0].ready and tasks[1].done())
        assert isinstance(tasks[1].exception(), PermissionError)
        assert two not in patient.nodes
        assert stat.S_IMODE((patient.directory / "nodes.yaml").stat().st_mode) == 0o600
        assert set(load(patient.directory / "nodes.yaml")) == {one}
        port = patient.endpoint_port
        await patient.close()
        await until(lambda: not nodes[0].ready)
        patient = Application("patient", tmp_path / "patient", endpoint_port=port)
        await patient.start()
        await until(lambda: nodes[0].ready and patient.nodes[one]["status"] == "online")
        assert not patient.node_registry.requests()
        await patient.action("node.remove", {"id": one})
        await until(lambda: tasks[0].done())
        assert tasks[0].exception() is None
        assert not patient.nodes and not load(patient.directory / "nodes.yaml")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await patient.close()


@pytest.mark.sdk
@pytest.mark.gpu
@pytest.mark.asyncio
async def test_approved_node_video_goes_directly_to_surgeon(tmp_path, enrolled_node):
    from telesurgery.server.application import Application
    from telesurgery_core.configuration import save

    directory = tmp_path / "node"
    save(
        directory / "devices.yaml",
        {
            "cameras": [
                {
                    "id": "fixture",
                    "name": "Remote camera",
                    "kind": "synthetic",
                    "source": "synthetic",
                    "width": 320,
                    "height": 240,
                    "fps": 30,
                }
            ]
        },
    )
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    try:
        await patient.start()
        node, key = await enrolled_node(patient, directory)
        await surgeon.start()
        admission = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", "Observer", False)
        await patient.action("access.approve", {"id": admission["id"]})
        camera = f"{key}:fixture"
        await until(lambda: camera in {c["id"] for c in surgeon.remote_status.get("cameras", [])})
        await surgeon.action("view", {"cameras": [camera]})
        await patient.action("camera.start", {"id": camera, "settings": {"codec": "h264"}})
        await until(
            lambda: (
                surgeon.media.feeds.get(camera) and surgeon.media.feeds[camera].benchmark.frames > 5
            )
        )
        assert camera not in patient.media.feeds
        assert node.video.viewers
        route = await surgeon.remote.call("viewer.ticket", {"camera": camera})
        assert route["port"] == node.video.address["port"] != patient.endpoint_port
        report = await patient.status(metrics=True, device=camera)
        assert report["video"][camera]["metrics"]["transport_frame_bytes"]["p50"] > 0
        await patient.action("access.revoke", {"id": admission["id"]})
        await until(lambda: not node.video.viewers and not node.video.tickets)
    finally:
        await surgeon.close()
        await patient.close()


@pytest.mark.asyncio
async def test_direct_video_tickets_scope_expiry_and_revocation(tmp_path):
    from telesurgery.nodes.video import VideoEndpoint
    from telesurgery_core.diagnostics.clock import Clock
    from telesurgery_core.transport.peer import Peer
    from telesurgery_core.transport.protocol import VideoHeader
    from telesurgery_core.transport.tls import client_context

    endpoint = VideoEndpoint(tmp_path, Clock())
    peers, received = [], []

    async def connect():
        async def reject(*args):
            raise PermissionError("No inbound commands")

        async def event(peer, name, params, payload):
            received.append((params, payload))

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", endpoint.address["port"], ssl=client_context()
        )
        peer = Peer(reader, writer, reject, event).start()
        peers.append(peer)
        return peer

    async def ticket():
        result = await endpoint.control(
            "video.ticket", {"owner": "surgeon", "camera": "one", "id": "node:one"}
        )
        return result["ticket"]

    try:
        await endpoint.start(0)
        viewer, other = await connect(), await connect()
        token = await ticket()
        await viewer.call("viewer.attach", {"ticket": token})
        with pytest.raises(RuntimeError, match="invalid"):
            await other.call("viewer.attach", {"ticket": token})
        for method in ("robot.move", "camera.start", "video.ticket", "subscribe"):
            with pytest.raises(RuntimeError, match="single viewer ticket"):
                await viewer.call(method, {})
        expired = await ticket()
        endpoint.tickets[expired]["expires"] = 0
        with pytest.raises(RuntimeError, match="expired"):
            await other.call("viewer.attach", {"ticket": expired})
        header = asdict(VideoHeader(0, 1, 32, 32))
        endpoint.publish("two", header, b"other frame", None)
        endpoint.publish("one", header, b"selected frame", None)
        await until(lambda: received)
        assert len(received) == 1 and received[0][0]["camera"] == "node:one"
        assert received[0][1] == b"selected frame"
        report = await endpoint.control("video.metrics", {"camera": "one"})
        sent = report["one"]["metrics"]["transport_frame_bytes"]["p50"]
        assert sent == received[0][0]["transport_bytes"]
        assert sent > len(received[0][1])
        outstanding = await ticket()
        await endpoint.control("video.revoke", {"owner": "surgeon", "cameras": ["one"]})
        await asyncio.wait_for(viewer.closed.wait(), 5)
        with pytest.raises(RuntimeError, match="invalid"):
            await other.call("viewer.attach", {"ticket": outstanding})
        assert not endpoint.viewers and not endpoint.tickets
    finally:
        for peer in peers:
            await peer.close()
        await endpoint.close()
