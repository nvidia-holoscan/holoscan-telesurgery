# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Feedback-paced input crosses the surgeon link and stops without new commands."""

import asyncio
import gzip
import json
import threading
import time

import pytest

pytest.importorskip("holoscan")
from telesurgery.controller.replay import Catalog, Rendezvous  # noqa: E402
from telesurgery.server.application import Application  # noqa: E402
from telesurgery_core.configuration import save  # noqa: E402
from telesurgery_robots.simulation.state import SimRobot  # noqa: E402
from websockets.sync.server import serve  # noqa: E402

pytestmark = [pytest.mark.sdk, pytest.mark.asyncio]


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("ending", ["complete", "cancel", "silent"])
async def test_remote_feedback_replay_reaches_grip_goal_and_stops(
    tmp_path, enrolled_node, ending, version
):
    robot = SimRobot()
    commands, holds = [], []

    def handle(socket):
        for raw in socket:
            request = json.loads(raw)
            if request["method"] == "jog_gripper":
                commands.append((time.monotonic(), request["params"]))
            if request["method"] == "hold":
                holds.append(time.monotonic())
            result = robot.apply(request)
            socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))

    directory = tmp_path / "replays/mira/keyboard"
    directory.mkdir(parents=True)
    rows = [
        {"t": i * 0.05, "keys": ["x" if i < 20 else "z"], "speeds": [20, 50, 40]} for i in range(40)
    ] + [{"t": 2.0, "keys": [], "speeds": [20, 50, 40]}]
    if version == 2:
        rows = [
            {"t": 0, "keys": ["x"], "speeds": [20, 50, 40], "grip": {"left": 0.2}},
            {"t": 1, "keys": ["z"], "speeds": [20, 50, 40], "grip": {"left": 0}},
        ]
    with gzip.open(directory / "mira.jsonl.gz", "wt") as output:
        output.write("\n".join(json.dumps(row) for row in rows))
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "environment": "mira",
                "device": "keyboard",
                "task": "Fixture grip",
                "replay_verified": True,
                "streams": {"mira": {"file": "mira.jsonl.gz", "initial": {"joints_deg": {}}}},
            }
        )
    )
    with serve(handle, "127.0.0.1", 0) as controller:
        thread = threading.Thread(target=controller.serve_forever, daemon=True)
        thread.start()
        host = tmp_path / "node"
        host.mkdir()
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
        surgeon = Application("surgeon", tmp_path / "surgeon")
        for app in (patient, surgeon):
            app.replay_catalog = Catalog(tmp_path / "replays")
            app.replay_barrier = Rendezvous(app.replay_catalog)
        try:
            await patient.start()
            _, node = await enrolled_node(patient, host)
            await surgeon.start()
            grant = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", "Replay", True)
            await patient.action("access.approve", {"id": grant["id"], "robot": True})
            async with asyncio.timeout(10):
                while surgeon.remote_status.get("status") != "approved":
                    await asyncio.sleep(0.02)
            key = f"{node}:mira"
            await surgeon.action("robot.acquire", {"id": key})
            call = surgeon.remote.call
            extra_polls = []
            rejected_inputs = []

            async def slow_call(method, *args, **kwargs):
                if method == "replay.poll" and commands:
                    extra_polls.append(time.monotonic())
                await asyncio.sleep(0.04)
                if (
                    method == "robot.move"
                    and version == 2
                    and ending == "complete"
                    and not rejected_inputs
                ):
                    # Exercise the real patient admission check: this packet is
                    # rejected before the node receives a command.
                    expired = {**args[0], "sent_at": args[0]["sent_at"] - 1}
                    rejected_inputs.append(expired)
                    args = (expired, *args[1:])
                result = await call(method, *args, **kwargs)
                await asyncio.sleep(0.04)
                return result

            surgeon.remote.call = slow_call
            await surgeon.action("replay.start", {"id": key, "recording": "mira/keyboard"})
            playback = surgeon.replays[key]
            assert not patient.replays  # The patient must not execute a local recording.

            async def heartbeat():
                while True:
                    await surgeon.action("replay.heartbeat", {"id": key})
                    await asyncio.sleep(0.05)

            alive = asyncio.create_task(heartbeat())
            queued = False
            try:
                async with asyncio.timeout(20):
                    while True:
                        result = await surgeon.action("replay.read", {"id": key})
                        assert result["feedback_paced"]
                        if result["request"]:
                            mode, command = result["request"]
                            if mode == "release":
                                await surgeon.action("robot.hold", {"id": key})
                            else:
                                params = {
                                    "id": key,
                                    "mode": mode,
                                    "command": {"velocity": command} if mode == "grip" else command,
                                    "replay": True,
                                    "replay_run": result["run"],
                                }
                                if ending == "complete" and not queued:
                                    # A local request can wait behind feedback I/O.
                                    # Revalidate this exact recorded input at dispatch.
                                    async with surgeon.control_lock:
                                        move = asyncio.create_task(
                                            surgeon.action("robot.move", params)
                                        )
                                        await asyncio.sleep(0.4)
                                    await move
                                    queued = True
                                else:
                                    await surgeon.action("robot.move", params)
                        if result["done"] or (ending != "complete" and len(commands) >= 5):
                            break
                if ending == "complete":
                    assert playback.finished
                    if version == 2:
                        assert len(rejected_inputs) == 1
                    assert commands
                    assert any(c[1] != commands[0][1] for c in commands)
                    assert robot._grippers()["left"] == pytest.approx(0, abs=0.04)
                    # Acknowledgements maintain the barrier during continuous
                    # input; do not pay another network round trip per sample.
                    assert len(extra_polls) <= max(3, len(commands) // 4)
                elif ending == "cancel":
                    await surgeon.action("replay.cancel", {"id": key})
                else:
                    alive.cancel()
                    await asyncio.gather(alive, return_exceptions=True)
                    await asyncio.sleep(0.45)
                    with pytest.raises(
                        (RuntimeError, TimeoutError), match="stopped polling|Replay stopped"
                    ):
                        await surgeon.action("replay.read", {"id": key})
                await surgeon.action("robot.hold", {"id": key})
            finally:
                alive.cancel()
                await asyncio.gather(alive, return_exceptions=True)
            count, stopped_at = len(commands), time.monotonic()
            assert holds and stopped_at - holds[-1] < 0.5
            await asyncio.sleep(0.2)
            assert len(commands) == count
            assert not robot.grip.rates
            with pytest.raises(RuntimeError, match="no longer current"):
                await surgeon.action("robot.move", params)
            # Manual input must still work after replay stops.
            await surgeon.action(
                "robot.move",
                {
                    "id": key,
                    "mode": "grip",
                    "command": {"velocity": {"left": 0.1}},
                },
            )
            assert len(commands) == count + 1
            await surgeon.action("robot.hold", {"id": key})
        finally:
            await surgeon.close()
            await patient.close()
            controller.shutdown()
            thread.join(timeout=2)
