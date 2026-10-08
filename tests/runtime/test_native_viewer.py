# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A native video connection inherits one camera grant and never gains control."""

import asyncio
from dataclasses import asdict

import pytest

pytest.importorskip("holoscan")
from telesurgery.server.application import Application  # noqa: E402
from telesurgery_core.transport.peer import Peer  # noqa: E402
from telesurgery_core.transport.protocol import VideoHeader  # noqa: E402
from telesurgery_core.transport.tls import client_context  # noqa: E402

pytestmark = [pytest.mark.sdk, pytest.mark.asyncio]


@pytest.mark.parametrize("ending", ["hide", "revoke", "disconnect"])
async def test_native_viewer_scope_direct_delivery_and_grant_lifetime(
    tmp_path, monkeypatch, ending, enrolled_node
):
    cameras = [
        {"id": key, "name": key, "width": 32, "height": 32, "kind": "fixture"}
        for key in ("one", "two")
    ]
    monkeypatch.setattr("telesurgery.nodes.local.discover", lambda *args: (cameras, []))
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    peers = []

    async def connection(events, route=None):
        async def reject(peer, method, params):
            raise PermissionError("No inbound actions")

        async def event(peer, name, params, payload):
            events.append((name, params, payload))

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", route["port"] if route else patient.endpoint_port, ssl=client_context()
        )
        peer = Peer(reader, writer, reject, event).start()
        peers.append(peer)
        return peer

    try:
        await patient.start()
        node, key = await enrolled_node(patient, tmp_path / "node")
        browser_events, native_events = [], []
        owner = await connection(browser_events)
        grant = await owner.call("access.request", {"name": "Viewer", "robot": False})
        with pytest.raises(RuntimeError, match="approval"):
            await owner.call("viewer.ticket", {"camera": f"{key}:one"})
        await patient.action("access.approve", {"id": grant["id"]})
        await owner.call("subscribe", {"cameras": [f"{key}:one"]})
        with pytest.raises(RuntimeError, match="Select"):
            await owner.call("viewer.ticket", {"camera": f"{key}:two"})
        ticket = await owner.call("viewer.ticket", {"camera": f"{key}:one"})
        native = await connection(native_events, ticket)
        await native.call("viewer.attach", {"ticket": ticket["ticket"]})
        replay = await connection([], ticket)
        with pytest.raises(RuntimeError, match="invalid"):
            await replay.call("viewer.attach", {"ticket": ticket["ticket"]})
        for method in ("subscribe", "robot.acquire", "access.request"):
            with pytest.raises(RuntimeError, match="single viewer ticket"):
                await native.call(method, {})
        await node.publish("one", asdict(VideoHeader(0, 1, 32, 32)), b"encoded fixture")
        async with asyncio.timeout(5):
            while not native_events:
                await asyncio.sleep(0.01)
        assert native_events[0][1]["camera"] == f"{key}:one"
        assert not browser_events  # The native stream bypasses the dashboard video connection.
        outstanding = await owner.call("viewer.ticket", {"camera": f"{key}:one"})
        if ending == "hide":
            await owner.call("subscribe", {"cameras": []})
        elif ending == "revoke":
            await patient.action("access.revoke", {"id": grant["id"]})
        else:
            await owner.close()
        await asyncio.wait_for(native.closed.wait(), 5)
        with pytest.raises(RuntimeError, match="invalid"):
            await replay.call("viewer.attach", {"ticket": outstanding["ticket"]})
        assert not node.video.viewers
    finally:
        for peer in peers:
            await peer.close()
        await patient.close()
