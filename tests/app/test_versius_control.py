# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Two surgeons hold separate arm leases through real TLS and controller graphs."""

import asyncio
import gzip
import json
import threading

import pytest

pytest.importorskip("holoscan")
from telesurgery.controller.replay import Catalog, Rendezvous  # noqa: E402
from telesurgery.server.application import Application  # noqa: E402
from telesurgery_core.configuration import save  # noqa: E402
from telesurgery_robots.simulation.state import SimRobot  # noqa: E402
from telesurgery_robots.versius import ARMS  # noqa: E402
from websockets.sync.server import serve  # noqa: E402

pytestmark = [pytest.mark.sdk, pytest.mark.asyncio]


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(0.05)


async def test_independent_versius_arm_leases_and_disconnect(tmp_path, enrolled_node):
    robots = {arm: SimRobot("versius") for arm in ARMS}
    robots["endoscope"].gripper_ranges = {}
    observed = []

    def handle(socket):
        arm = socket.request.path.strip("/")
        for raw in socket:
            request = json.loads(raw)
            observed.append((arm, request["method"]))
            result = robots[arm].apply(request)
            socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))

    with serve(handle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        node_dir = tmp_path / "node"
        node_dir.mkdir()
        save(
            node_dir / "devices.yaml",
            {
                "robots": [
                    {
                        "id": arm,
                        "name": f"Versius {arm} arm",
                        "kind": "versius-sim",
                        "uri": f"ws://127.0.0.1:{server.socket.getsockname()[1]}/{arm}",
                    }
                    for arm in robots
                ]
            },
        )
        patient = Application("patient", tmp_path / "patient", endpoint_port=0)
        surgeons = [Application("surgeon", tmp_path / str(i)) for i in range(2)]
        try:
            await patient.start()
            _, node = await enrolled_node(patient, node_dir)
            grants = []
            for i, surgeon in enumerate(surgeons):
                await surgeon.start()
                grant = await surgeon.connect(
                    f"127.0.0.1:{patient.endpoint_port}", f"Surgeon {i + 1}", True
                )
                grants.append(grant["id"])
                await patient.action("access.approve", {"id": grant["id"], "robot": True})
            await until(lambda: all(s.remote_status.get("status") == "approved" for s in surgeons))
            commands = [
                {"id": f"{node}:{arm}", "command": {"joints": [0.1] + [0] * 7}, "mode": "step"}
                for arm in ("left", "right")
            ]
            await asyncio.gather(
                *(
                    s.action("robot.acquire", {"id": c["id"]})
                    for s, c in zip(surgeons, commands, strict=True)
                )
            )
            await asyncio.gather(
                *(s.action("robot.move", c) for s, c in zip(surgeons, commands, strict=True))
            )
            assert patient.owners[commands[0]["id"]].owner == grants[0]
            assert patient.owners[commands[1]["id"]].owner == grants[1]
            with pytest.raises(RuntimeError, match="another|controlled|owns|control"):
                await surgeons[1].action("robot.move", commands[0])
            assert ("left", "set_joint_delta") in observed
            assert ("right", "set_joint_delta") in observed
            # Replay is a shared start barrier; it never acquires the other arm.
            directory = tmp_path / "replays/versius/keyboard"
            directory.mkdir(parents=True)
            streams = {}
            for arm in ("left", "right"):
                with gzip.open(directory / f"{arm}.jsonl.gz", "wt") as output:
                    output.write(json.dumps({"t": 0, "keys": [], "speeds": [20, 50, 40]}))
                streams[arm] = {"file": f"{arm}.jsonl.gz", "initial": {"joints_deg": {}}}
            (directory / "manifest.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "environment": "versius",
                        "device": "keyboard",
                        "task": "Fixture handoff",
                        "replay_verified": True,
                        "streams": streams,
                    }
                )
            )
            for app in [patient, *surgeons]:
                app.replay_catalog = Catalog(tmp_path / "replays")
                app.replay_barrier = Rendezvous(app.replay_catalog)
            with pytest.raises(PermissionError, match="Acquire"):
                await surgeons[1].action(
                    "replay.start",
                    {
                        "id": commands[0]["id"],
                        "recording": "versius/keyboard",
                    },
                )
            await surgeons[0].action(
                "replay.start",
                {
                    "id": commands[0]["id"],
                    "recording": "versius/keyboard",
                },
            )
            waiting = await surgeons[0].action("replay.read", {"id": commands[0]["id"]})
            assert waiting["waiting"] and waiting["request"] is None
            await surgeons[1].action(
                "replay.start",
                {
                    "id": commands[1]["id"],
                    "recording": "versius/keyboard",
                },
            )
            ready = await surgeons[1].action("replay.read", {"id": commands[1]["id"]})
            assert not ready["waiting"] and ready["request"] is None
            await surgeons[0].action("disconnect", {})
            await until(lambda: patient.owners[commands[0]["id"]].owner is None)
            assert ("left", "hold") in observed
            assert patient.owners[commands[1]["id"]].owner == grants[1]
            with pytest.raises(RuntimeError, match="Replay stopped"):
                await surgeons[1].action("replay.read", {"id": commands[1]["id"]})
            await surgeons[1].action("robot.move", commands[1])
        finally:
            for surgeon in surgeons:
                await surgeon.close()
            await patient.close()
            server.shutdown()
            thread.join(timeout=2)
