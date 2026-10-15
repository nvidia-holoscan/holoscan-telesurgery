# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Feedback-paced input crosses the surgeon link and stops without new commands."""

import asyncio
import gzip
import json
import shutil
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


@pytest.mark.parametrize("updated_patient", [True, False])
async def test_checkpoint_reads_new_measured_feedback_even_immediately_after_ack(
    tmp_path, updated_patient
):
    from types import SimpleNamespace

    from telesurgery.controller.checkpoint_replay import CheckpointPlayback
    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.adapters.simulation import FrankaSimulation

    app = Application("surgeon", tmp_path)
    key = "node:franka"
    goal = {
        "frame": "base",
        "end_effector": "TCP",
        "position_m": [0.01, 0, 0],
        "orientation_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    }
    robot = {"kind": "franka-sim", "controls": controls(FrankaSimulation({"uri": "unused"}), {})}
    playback = CheckpointPlayback(
        robot,
        {"device": "haply"},
        "franka",
        [{"t": 0, "speeds": [20, 50, 40], "tool_pose": goal}],
        "run",
    )
    playback.barrier = {"elapsed": 0, "done": False}
    playback.polled_at = time.monotonic()
    app.tokens[key] = "token"
    app.replays[key] = playback
    app.remote_status = {"status": "approved", "robot": True}
    app.robot_state[key] = {
        "sequence": 10,
        "control_active": False,
        "tool_pose": {**goal, "position_m": [0, 0, 0]},
    }
    calls = []

    async def poll(method, params):
        calls.append(method)
        if method == "replay.cancel":
            return True
        assert params["fresh"] is True
        return {
            "elapsed": 0.1,
            "done": False,
            **({"checkpoint": 0} if updated_patient else {}),
            "state": {"sequence": 11, "control_active": False, "tool_pose": goal},
        }

    app.remote = SimpleNamespace(call=poll)
    if not updated_patient:
        with pytest.raises(RuntimeError, match="Patient service.*restart"):
            await app._replay_action("replay.read", {"id": key})
        assert key not in app.replays
        assert calls == ["replay.poll", "replay.cancel"]
        assert not playback.finished
        return
    result = await app._replay_action("replay.read", {"id": key})
    assert calls == ["replay.poll"]
    assert result["state"]["sequence"] == 11
    assert result["request"] == ("release", {})
    assert playback.finished


@pytest.mark.parametrize(
    "version,environment,device",
    [(1, "mira", "keyboard")]
    + [
        (2, environment, device)
        for environment in ("mira", "franka", "versius")
        for device in ("keyboard", "gamepad", "haply")
    ],
)
@pytest.mark.parametrize("ending", ["complete", "cancel", "silent"])
async def test_remote_feedback_replay_reaches_grip_goal_and_stops(
    tmp_path, enrolled_node, ending, version, environment, device
):
    robot = SimRobot(environment)
    grip = "left" if environment == "mira" else "hand"
    role = "left" if environment == "versius" else environment
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

    directory = tmp_path / "replays" / environment / device
    directory.mkdir(parents=True)
    rows = [
        {"t": i * 0.05, "keys": ["x" if i < 20 else "z"], "speeds": [20, 50, 40]} for i in range(40)
    ] + [{"t": 2.0, "keys": [], "speeds": [20, 50, 40]}]
    if version == 2:
        rows = [
            {"t": 0, "keys": ["x"], "speeds": [20, 50, 40], "grip": {grip: 0.2}},
            {"t": 1, "keys": ["z"], "speeds": [20, 50, 40], "grip": {grip: 0}},
        ]
    with gzip.open(directory / "input.jsonl.gz", "wt") as output:
        output.write("\n".join(json.dumps(row) for row in rows))
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "version": version,
                "environment": environment,
                "device": device,
                "task": "Fixture grip",
                "replay_verified": True,
                "streams": {role: {"file": "input.jsonl.gz", "initial": {"joints_deg": {}}}},
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
                        "id": role,
                        "name": "MIRA",
                        "kind": environment + "-sim",
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
            key = f"{node}:{role}"
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
            await surgeon.action(
                "replay.start", {"id": key, "recording": f"{environment}/{device}"}
            )
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
                    assert robot._grippers()[grip] == pytest.approx(0, abs=0.04)
                    # Acknowledgements maintain the barrier during continuous
                    # input; do not pay another network round trip per sample.
                    if version == 1:
                        assert len(extra_polls) <= max(3, len(commands) // 4)
                    else:
                        assert len(extra_polls) >= len(commands) - 1
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
                    "command": {"velocity": {grip: 0.1}},
                },
            )
            assert len(commands) == count + 1
            await surgeon.action("robot.hold", {"id": key})
        finally:
            await surgeon.close()
            await patient.close()
            controller.shutdown()
            thread.join(timeout=2)


@pytest.mark.parametrize(
    "left_device,right_device", [("haply", "haply"), ("gamepad", "keyboard"), ("keyboard", "haply")]
)
@pytest.mark.parametrize("independent", [False, True])
async def test_two_surgeons_release_donor_only_after_delayed_receiver_grasps(
    tmp_path, enrolled_node, left_device, right_device, independent
):
    robots = {role: SimRobot("versius") for role in ("left", "right")}
    for robot in robots.values():
        robot.finger_target = 0.004  # Start with a small opening, then close.
    events = []
    pose = {
        "frame": "base",
        "end_effector": "TCP",
        "position_m": [0, 0, 0],
        "orientation_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    }

    def handle(socket):
        role = socket.request.path.strip("/")
        for raw in socket:
            request = json.loads(raw)
            if request["method"] == "jog_gripper":
                events.append((role, request["params"]["velocity"]["hand"]))
                if independent and role == "left" and request["params"]["velocity"]["hand"] > 0:
                    assert robots["right"]._grippers()["hand"] == pytest.approx(0.1)
                    assert not robots["right"].grip.rates
            if independent:
                robots[role].feedback = {
                    "tool_pose": pose,
                    "grippers": {"hand": max(0.1, robots[role].finger_target / 0.04)},
                }
            result = robots[role].apply(request)
            socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}))

    directory = tmp_path / "replays/versius/haply"
    directory.mkdir(parents=True)
    streams = {}
    for role in robots:
        targets = ([{"hold_s": 0.8}] if role == "right" else []) + [
            {"grip": {"hand": 0}},
            {"barrier": 1},
            {"grip": {"hand": 0.1}} if role == "left" else {"hold_s": 0.1},
        ]
        if independent:
            targets = [{"tool_pose": pose}, {"grip": {"hand": 0}}, {"hold_s": 0.1}]
            if role == "right":
                targets += [{"handoff": "take"}, {"hold_s": 0.1}]
        with gzip.open(directory / f"{role}.jsonl.gz", "wt") as output:
            for i, target in enumerate(targets):
                output.write(json.dumps({"t": i, "speeds": [20, 50, 40], **target}) + "\n")
        streams[role] = {"file": f"{role}.jsonl.gz", "initial": {"joints_deg": {}}}
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "environment": "versius",
                "device": "haply",
                "barriers": 0 if independent else 1,
                "independent_actions": independent,
                "task": "Handoff fixture",
                "handoff_group": "handoff-fixture",
                "replay_verified": True,
                "streams": streams,
            }
        )
    )
    for device in ("keyboard", "gamepad"):
        destination = directory.parent / device
        shutil.copytree(directory, destination)
        manifest = json.loads((destination / "manifest.json").read_text())
        manifest["device"] = device
        (destination / "manifest.json").write_text(json.dumps(manifest))
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
                        "id": role,
                        "name": role,
                        "kind": "versius-sim",
                        "uri": f"ws://127.0.0.1:{controller.socket.getsockname()[1]}/{role}",
                    }
                    for role in robots
                ]
            },
        )
        patient = Application("patient", tmp_path / "patient", endpoint_port=0)
        surgeons = {role: Application("surgeon", tmp_path / role) for role in robots}
        for app in (patient, *surgeons.values()):
            app.replay_catalog = Catalog(tmp_path / "replays")
            app.replay_barrier = Rendezvous(app.replay_catalog)
        try:
            await patient.start()
            _, node = await enrolled_node(patient, host)
            for role, surgeon in surgeons.items():
                await surgeon.start()
                grant = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", role, True)
                await patient.action("access.approve", {"id": grant["id"], "robot": True})
                async with asyncio.timeout(10):
                    while surgeon.remote_status.get("status") != "approved":
                        await asyncio.sleep(0.02)
                await surgeon.action("robot.acquire", {"id": f"{node}:{role}"})
            call = surgeons["right"].remote.call

            async def slow_call(*args, **kwargs):
                await asyncio.sleep(0.05)
                result = await call(*args, **kwargs)
                await asyncio.sleep(0.05)
                return result

            surgeons["right"].remote.call = slow_call
            waited = []

            async def play(role, surgeon):
                params = {"id": f"{node}:{role}"}
                device = left_device if role == "left" else right_device
                await surgeon.action("replay.start", {**params, "recording": f"versius/{device}"})
                while True:
                    await surgeon.action("replay.heartbeat", params)
                    result = await surgeon.action("replay.read", params)
                    if result.get("waiting_peer"):
                        waited.append(role)
                    if result["request"]:
                        mode, command = result["request"]
                        if mode == "release":
                            await surgeon.action("robot.hold", params)
                        else:
                            if not independent and role == "left" and command["hand"] > 0:
                                assert robots["right"]._grippers()["hand"] <= 0.002
                            await surgeon.action(
                                "robot.move",
                                {
                                    **params,
                                    "mode": mode,
                                    "command": {"velocity": command},
                                    "replay": True,
                                    "replay_run": result["run"],
                                },
                            )
                    if result["done"]:
                        return
                    await asyncio.sleep(0.01)

            async with asyncio.timeout(15):
                if independent:
                    renewals = [
                        asyncio.create_task(_renew_control(s, f"{node}:{role}"))
                        for role, s in surgeons.items()
                    ]
                    try:
                        await play("left", surgeons["left"])
                        assert f"{node}:left" not in surgeons["left"].replays
                        await asyncio.sleep(0.6)  # Left replay heartbeat has ended.
                        await play("right", surgeons["right"])
                    finally:
                        for task in renewals:
                            task.cancel()
                        await asyncio.gather(*renewals, return_exceptions=True)
                else:
                    await asyncio.gather(*(play(role, s) for role, s in surgeons.items()))
            assert ("left" in waited) is not independent
            assert any(role == "left" and rate > 0 for role, rate in events)
            assert robots["left"]._grippers()["hand"] == pytest.approx(
                1.0 if independent else 0.1, abs=0.005
            )
        finally:
            for surgeon in surgeons.values():
                await surgeon.close()
            await patient.close()
            controller.shutdown()
            thread.join(timeout=2)


async def _renew_control(surgeon, key):
    while True:
        await surgeon.action("robot.renew", {"id": key})
        await asyncio.sleep(0.3)
