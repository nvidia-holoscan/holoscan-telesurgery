# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Standalone nodes use pinned TLS, exclude unpaired clients, and survive restarts."""

import asyncio
import json
import stat
from dataclasses import asdict

import pytest
from telesurgery.nodes.pairing import credentials, endpoint
from telesurgery_core.configuration import load


def test_pairing_and_addresses():
    assert endpoint("room-node") == ("room-node", 7448, "room-node:7448")
    assert endpoint(" patient-host ", 7447) == ("patient-host", 7447, "patient-host:7447")
    assert endpoint("patient-host:7555", 7447) == ("patient-host", 7555, "patient-host:7555")
    assert endpoint("[::1]:7555") == ("::1", 7555, "[::1]:7555")
    for address in ("", "host:0", "host:65536", "http://host", "user@host", "host/path"):
        with pytest.raises(ValueError):
            endpoint(address)
    with pytest.raises(ValueError, match="complete pairing code"):
        credentials("1234")


async def until(predicate):
    async with asyncio.timeout(25):
        while not predicate():
            await asyncio.sleep(0.05)


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


@pytest.mark.sdk
@pytest.mark.gpu
@pytest.mark.asyncio
async def test_pairing_video_restart_and_identity_checks(tmp_path):
    from telesurgery.nodes.standalone import NodeServer
    from telesurgery.server.application import Application
    from telesurgery_core.transport.peer import Peer
    from telesurgery_core.transport.tls import client_context

    directory = tmp_path / "node"
    directory.mkdir()
    (directory / "devices.json").write_text(
        json.dumps(
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
            }
        )
    )
    node = NodeServer(directory, 0)
    # Reserve a port before the node exists: --nodes must list and track it offline.
    import socket

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    node.port = port
    address = f"127.0.0.1:{port}"
    patient = Application(
        "patient", tmp_path / "patient", endpoint_port=0, nodes=[address, address]
    )
    surgeon = Application("surgeon", tmp_path / "surgeon")
    unpaired = None
    try:
        await patient.start()
        assert len(patient.node_registry.configs) == 1
        key = next(iter(patient.node_registry.configs))
        assert patient.nodes[key]["status"] == "offline"
        await node.start()
        await until(lambda: patient.nodes[key]["status"] == "unpaired")
        assert patient.nodes[key].get("cameras") is None
        await surgeon.start()
        address = f"127.0.0.1:{node.port}"
        code = node.pairing_code
        reader, writer = await asyncio.open_connection("127.0.0.1", node.port, ssl=client_context())

        async def reject(*args):
            raise PermissionError("unpaired client")

        unpaired = Peer(reader, writer, reject).start()
        for method, params in (
            ("inventory", {}),
            ("camera.start", {"id": "fixture"}),
            ("robot.prepare", {}),
        ):
            with pytest.raises(RuntimeError, match="Pair this node"):
                await unpaired.call(method, params)
        bad_code = code[:65] + "A" * 43
        with pytest.raises(RuntimeError, match="Incorrect pairing"):
            await patient.action("node.connect", {"address": address, "code": bad_code})
        assert "token" not in patient.node_registry.configs[key]
        with pytest.raises(PermissionError, match="identity changed"):
            await patient.action("node.connect", {"address": address, "code": "0" * 64 + code[64:]})
        result = await patient.action("node.connect", {"address": address, "code": code})
        assert result["id"] == key
        with pytest.raises(ValueError, match="already connected"):
            await patient.action("node.connect", {"address": address, "code": code})
        with pytest.raises(RuntimeError, match="already connected"):
            await unpaired.call("node.attach", {"token": node.token})
        assert stat.S_IMODE((patient.directory / "nodes.yaml").stat().st_mode) == 0o600
        assert stat.S_IMODE((directory / "service.yaml").stat().st_mode) == 0o600
        visible = json.dumps(await patient.status())
        assert node.token not in visible and node.pairing_code not in visible
        assert patient.nodes[key]["sdk"]
        camera = f"{key}:fixture"
        admission = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", "Observer", False)
        await patient.action("access.approve", {"id": admission["id"]})
        await until(lambda: camera in {c["id"] for c in surgeon.remote_status.get("cameras", [])})
        await surgeon.action("view", {"cameras": [camera]})
        await patient.action("camera.start", {"id": camera})
        await until(
            lambda: (
                surgeon.media.feeds.get(camera) and surgeon.media.feeds[camera].benchmark.frames > 5
            )
        )
        # Video travels node → surgeon. The coordinator receives no payloads.
        assert camera not in patient.media.feeds
        assert node.video.viewers
        assert all(item["camera"] == "fixture" for item in node.video.viewers.values())
        async with asyncio.timeout(10):
            while True:
                report = await patient.status(metrics=True, device=camera)
                path = report["video"][camera]["path"]
                if path.get("total"):
                    break
                await asyncio.sleep(0.1)
        assert "node_transport_ms" not in path["stages"]
        assert "transport_ms" not in path["stages"]
        await patient.action("access.revoke", {"id": admission["id"]})
        await until(lambda: not node.video.viewers)
        assert not node.video.tickets
        await patient.close()
        await until(lambda: node.peer is None and not node.node.local.workers)
        patient = Application("patient", tmp_path / "patient", endpoint_port=0, nodes=[address])
        assert len(patient.node_registry.configs) == 1
        await patient.start()
        await until(lambda: patient.nodes.get(key, {}).get("status") == "online")
        port = node.port
        await node.close()
        await until(lambda: patient.nodes[key]["status"] == "offline")
        node = NodeServer(directory, port)
        await node.start()
        assert node.pairing_code == code
        await until(lambda: patient.nodes[key]["status"] == "online")
        await patient.action("camera.start", {"id": camera})
        await until(lambda: node.node.local.workers["fixture"]["frames"] > 5)
        with pytest.raises(ValueError, match="local host"):
            await patient.action("node.remove", {"id": "host"})
        await patient.action("node.remove", {"id": key})
        await until(lambda: node.peer is None and not node.node.local.workers)
        assert key not in patient.nodes
        assert camera not in patient.media.feeds
        assert not patient.node_registry.configs
        assert load(patient.directory / "nodes.yaml") == {}
        await asyncio.sleep(2.1)
        assert node.peer is None
        assert node.token not in (patient.directory / f"connect-{key}.log").read_text()
    finally:
        if unpaired:
            await unpaired.close()
        await surgeon.close()
        await patient.close()
        await node.close()
