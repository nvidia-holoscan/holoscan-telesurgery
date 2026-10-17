# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Real TLS endpoints and Holoscan graphs; robot fixture replaces physical hardware only."""

import asyncio
import json
import threading
import time

import pytest

pytest.importorskip("holoscan")
from telesurgery.server.application import Application  # noqa: E402
from telesurgery_core.configuration import save  # noqa: E402
from telesurgery_robots.simulation.state import SimRobot  # noqa: E402
from websockets.sync.server import serve  # noqa: E402

pytestmark = [pytest.mark.sdk, pytest.mark.asyncio]


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.05)


async def test_removed_camera_does_not_block_selecting_replacement(
    tmp_path, monkeypatch, enrolled_node
):
    # Exercise removal from discovery without retaining an active camera worker.
    cameras = [
        {"id": key, "name": key, "kind": "fixture", "auto_start": False}
        for key in ("old", "retained")
    ]
    monkeypatch.setattr("telesurgery.nodes.local.discover", lambda *_: (list(cameras), []))
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    try:
        await patient.start()
        _, key = await enrolled_node(patient, tmp_path / "node")
        await surgeon.start()
        grant = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", "Observer", False)
        await patient.action("access.approve", {"id": grant["id"]})
        await until(lambda: surgeon.remote_status.get("status") == "approved")
        await surgeon.action("view", {"cameras": [f"{key}:old", f"{key}:retained"]})
        cameras[0] = {"id": "new", "name": "new", "kind": "fixture", "auto_start": False}
        await until(lambda: surgeon.subscribed == {f"{key}:retained"})
        assert surgeon.selected == {f"{key}:old", f"{key}:retained"}
        await surgeon.action("view", {"cameras": [f"{key}:new", f"{key}:retained"]})
        assert surgeon.selected == {f"{key}:new", f"{key}:retained"}
        assert patient.peers[grant["id"]]["selected"] == surgeon.selected
    finally:
        await surgeon.close()
        await patient.close()


async def test_patient_restart_restores_selection_but_revocation_stops_rejoin(
    tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    patient = Application(
        "patient", tmp_path / "patient", endpoint_port=0, endpoint_host="127.0.0.1"
    )
    surgeon = Application("surgeon", tmp_path / "surgeon")
    inventory = {"cameras": [{"id": "node:camera", "name": "Camera"}], "robots": [], "nodes": []}
    monkeypatch.setattr(patient, "inventory", lambda: inventory)
    monkeypatch.setattr(surgeon.streams, "select", AsyncMock())
    try:
        await patient.start()
        await surgeon.start()
        address = f"127.0.0.1:{patient.endpoint_port}"
        grant = await surgeon.connect(address, "Observer", False)
        await patient.action("access.approve", {"id": grant["id"]})
        await until(lambda: surgeon.remote_status.get("status") == "approved")
        await surgeon.action("view", {"cameras": ["node:camera"]})
        port = patient.endpoint_port
        await patient.close()
        await until(lambda: surgeon.remote_status.get("status") == "reconnecting")
        assert "lost" in surgeon.connection_notice
        assert surgeon.join_request == {"address": address, "name": "Observer", "robot": False}
        assert not surgeon.tokens
        patient = Application(
            "patient", tmp_path / "patient", endpoint_port=port, endpoint_host="127.0.0.1"
        )
        monkeypatch.setattr(patient, "inventory", lambda: inventory)
        await patient.start()
        await until(
            lambda: (
                surgeon.remote_status.get("status") == "approved"
                and surgeon.subscribed == {"node:camera"}
            )
        )
        assert "restored" in surgeon.connection_notice
        assert not surgeon.tokens and not surgeon.replays
        assert surgeon.selected == {"node:camera"}
        assert patient.peers[surgeon.remote_status["id"]]["selected"] == {"node:camera"}
        await patient.action("access.revoke", {"id": surgeon.remote_status["id"]})
        await until(lambda: surgeon.remote_status.get("status") == "revoked")
        assert not surgeon.reconnect_enabled
        assert "ended your access" in surgeon.connection_notice
        await asyncio.sleep(2.2)
        assert surgeon.remote_status["status"] == "revoked"
        assert (await surgeon.connect(address, "Observer", False))["status"] == "pending"
        await surgeon.action("disconnect", {})
        assert not surgeon.reconnect_enabled and surgeon.reconnect_task is None
    finally:
        await surgeon.close()
        await patient.close()


async def test_returning_surgeon_waits_for_previous_connection_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr("telesurgery.nodes.local.discover", lambda *_: ([], []))
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    closing, release = asyncio.Event(), asyncio.Event()
    original = patient._close_viewers
    previous = returning = None

    async def delayed_cleanup(owner, cameras=None):
        if owner == previous:
            closing.set()
            await release.wait()
        await original(owner, cameras)

    monkeypatch.setattr(patient, "_close_viewers", delayed_cleanup)
    try:
        await patient.start()
        await surgeon.start()
        address = f"127.0.0.1:{patient.endpoint_port}"
        first = await surgeon.connect(address, "Surgeon", False)
        previous = first["id"]
        await patient.action("access.approve", {"id": previous})
        await surgeon.action("disconnect", {})
        await asyncio.wait_for(closing.wait(), 3)
        returning = asyncio.create_task(surgeon.connect(address, "Surgeon", False))
        await asyncio.sleep(0.1)
        assert not returning.done()
        release.set()
        second = await asyncio.wait_for(returning, 3)
        assert second["status"] == "approved"
        assert second["id"] != previous
        assert set(patient.access.surgeons) == {second["id"]}
    finally:
        release.set()
        if returning:
            await asyncio.gather(returning, return_exceptions=True)
        await surgeon.close()
        await patient.close()


async def test_silent_surgeon_expires_and_same_identity_can_return(tmp_path, monkeypatch):
    from telesurgery_core.transport.peer import PREFIX
    from telesurgery_core.transport.tls import client_context

    monkeypatch.setattr("telesurgery_core.transport.peer.RECEIVE_TIMEOUT", 1)
    monkeypatch.setattr("telesurgery_core.transport.peer.PROBE_INTERVAL", 0.1)
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    writer = None
    try:
        await patient.start()
        await surgeon.start()
        address = f"127.0.0.1:{patient.endpoint_port}"
        _, writer = await asyncio.open_connection(
            "127.0.0.1", patient.endpoint_port, ssl=client_context()
        )
        request = json.dumps(
            {
                "type": "request",
                "id": "first",
                "method": "access.request",
                "params": {"name": "Surgeon", "robot": True, "credential": surgeon._identity()},
            }
        ).encode()
        writer.write(PREFIX.pack(len(request), 0) + request)
        await writer.drain()
        await until(lambda: bool(patient.access.surgeons))
        previous = next(iter(patient.access.surgeons))
        await patient.action("access.approve", {"id": previous, "robot": True})
        # Preserve the live duplicate-identity guard.
        with pytest.raises(RuntimeError, match="already connected"):
            await surgeon.connect(address, "Surgeon", True)
        # Leave the old socket open, but send no more data, like a lost laptop.
        await until(lambda: previous not in patient.access.surgeons)
        assert not patient.access.identities
        returning = await surgeon.connect(address, "Surgeon", True)
        assert returning["status"] == "approved" and returning["robot"]
        assert returning["id"] != previous
        assert set(patient.access.surgeons) == {returning["id"]}
    finally:
        if writer:
            writer.close()
            await writer.wait_closed()
        await surgeon.close()
        await patient.close()


async def test_two_surgeons_admission_handoff_and_disconnect(tmp_path, enrolled_node):
    observed = []
    robot = SimRobot()
    fail_hold = [False]

    def handle(socket):
        for raw in socket:
            request = json.loads(raw)
            observed.append(request["method"])
            if request["method"] == "hold" and fail_hold[0]:
                fail_hold[0] = False
                socket.send(
                    json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": "hold failed"})
                )
                continue
            result = robot.apply(request)
            socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))

    with serve(handle, "127.0.0.1", 0) as controller:
        thread = threading.Thread(target=controller.serve_forever, daemon=True)
        thread.start()
        host = tmp_path / "node"
        host.mkdir(parents=True)
        save(
            host / "devices.yaml",
            {
                "robots": [
                    {
                        "id": "mira",
                        "name": "MIRA",
                        "kind": "mira-sim",
                        "uri": f"ws://127.0.0.1:{controller.socket.getsockname()[1]}",
                    }
                ]
            },
        )
        patient = Application("patient", tmp_path / "patient", endpoint_port=0)
        one = Application("surgeon", tmp_path / "one")
        two = Application("surgeon", tmp_path / "two")
        services = []
        try:
            for app in [patient, one, two]:
                await app.start()
                services.append(app)
            node, node_id = await enrolled_node(patient, host)
            robot_id = f"{node_id}:mira"
            address = f"127.0.0.1:{patient.endpoint_port}"
            first = await one.connect(address, "Same name", True)
            second = await two.connect(address, "Same name", True)
            assert first["id"] != second["id"]
            assert "robots" not in await one.remote.call("status")
            with pytest.raises(RuntimeError, match="approval"):
                await one.remote.call("subscribe", {"cameras": []})
            await patient.action("access.approve", {"id": first["id"], "robot": True})
            await patient.action("access.approve", {"id": second["id"], "robot": True})
            await until(
                lambda: one.remote_status["status"] == two.remote_status["status"] == "approved"
            )
            command = {
                "id": robot_id,
                "command": {"left": [1, 0, 0, 0, 0], "right": [0, 0, 0, 0, 0]},
            }
            replies = await asyncio.gather(
                one.action("robot.acquire", {"id": robot_id}),
                two.action("robot.acquire", {"id": robot_id}),
                return_exceptions=True,
            )
            assert sum(isinstance(reply, Exception) for reply in replies) == 1, replies
            winner, other = (one, two) if not isinstance(replies[0], Exception) else (two, one)
            await winner.action("robot.move", command)
            assert "timings" not in await winner.status()
            timing = (await winner.status(metrics=True))["timings"]
            assert timing["patient_round_trip_ms"]["count"] > 0
            assert timing["control_ack_ms"]["count"] == 1
            assert timing["control_ack_ms"]["p50"] > 0
            assert (await winner.status(metrics=True))["robot_timings"][robot_id]["count"] == 1
            assert (await patient.status(metrics=True))["robot_timings"][robot_id]["count"] == 1
            assert not (await other.status(metrics=True))["robot_timings"]
            assert (await other.status(metrics=True))["timings"]["control_ack_ms"]["count"] == 0
            original = winner.tokens[robot_id]
            assert observed.count("set_mira_cartesian_delta") == 1
            await winner.action("metrics.reset", {})
            assert winner.tokens[robot_id] == original
            assert not (await winner.status(metrics=True))["robot_timings"]
            assert patient.owners[robot_id].owner == winner.remote_status["id"]
            assert (await winner.status(metrics=True))["timings"]["control_ack_ms"]["count"] == 0
            fail_hold[0] = True
            with pytest.raises(RuntimeError, match="hold failed"):
                await winner.action("robot.release", {"id": robot_id})
            assert robot_id not in winner.tokens
            assert not patient.owners[robot_id].ready
            with pytest.raises(RuntimeError, match="Previous stop was not confirmed"):
                await other.action("robot.acquire", {"id": robot_id})
            await patient.action("robot.revoke", {"id": robot_id})
            assert patient.owners[robot_id].ready
            await other.action("robot.acquire", {"id": robot_id})
            await other.action("robot.move", command)
            assert observed.count("set_mira_cartesian_delta") == 2
            with pytest.raises(RuntimeError, match="expired|belongs"):
                await winner.remote.call(
                    "robot.move",
                    {**command, "token": original, "sequence": 100, "sent_at": time.time()},
                )
            # A transport loss stops the device but reserves the surgeon's lock.
            previous_id = other.remote_status["id"]
            previous_token = other.tokens[robot_id]
            previous_sequence = patient.owners[robot_id].sequence
            await other.remote.close()
            await until(lambda: previous_id not in patient.access.surgeons)
            await until(lambda: other.remote_status.get("status") == "reconnecting")
            assert patient.owners[robot_id].owner == previous_id
            with pytest.raises(RuntimeError, match="another surgeon"):
                await winner.action("robot.acquire", {"id": robot_id})
            resumed = await other.connect(address, "Same name", True)
            assert resumed["status"] == "approved"
            assert other.tokens[robot_id] == previous_token
            assert other.sequences[robot_id] == previous_sequence
            assert "control_tokens" not in resumed and "control_sequences" not in resumed
            await until(lambda: "robots" in other.remote_status)
            await other.action("robot.hold", {"id": robot_id})
            assert observed.count("set_mira_cartesian_delta") == 2
            await other.action("robot.move", command)
            assert observed.count("set_mira_cartesian_delta") == 3
            await other.action("disconnect", {})
            await until(lambda: patient.owners[robot_id].owner is None)
            assert "hold" in observed
            await winner.action("robot.acquire", {"id": robot_id})
            await winner.action("robot.move", command)
            winner_id = (first if winner is one else second)["id"]
            await patient.action("access.revoke", {"id": winner_id})
            assert patient.owners[robot_id].owner is None
            assert "robots" not in await winner.remote.call("status")
            with pytest.raises(RuntimeError, match="approval"):
                await winner.action("robot.acquire", {"id": robot_id})
            assert (await winner.status(metrics=True))["timings"]["control_ack_ms"]["count"] == 1
            await other.connect(address, "New session", False)
            assert (await other.status(metrics=True))["timings"]["control_ack_ms"]["count"] == 0
        finally:
            # Patient shutdown must close active TLS clients before waiting on its listener.
            for app in services:
                await asyncio.wait_for(app.close(), 10)
            controller.shutdown()
            thread.join(timeout=2)
