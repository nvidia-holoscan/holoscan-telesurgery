# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Recorded input uses normal mappings and releases ownership when replay fails."""

import gzip
import importlib.util
import json
from pathlib import Path

import pytest
from aiohttp import web
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import MiraSimulation

spec = importlib.util.spec_from_file_location(
    "replay_controller", Path(__file__).resolve().parents[2] / "scripts/replay_controller.py"
)
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


@pytest.fixture
def recording(tmp_path):
    rows = [
        {"t": 0, "keys": ["w"], "speeds": [20, 50, 40]},
        {"t": 0.06, "keys": [], "speeds": [20, 50, 40]},
    ]
    with gzip.open(tmp_path / "input.jsonl.gz", "wt") as output:
        output.write("\n".join(json.dumps(row) for row in rows))
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "environment": "franka",
                "device": "keyboard",
                "task": "Short translation",
                "streams": {
                    "arm": {"file": "input.jsonl.gz", "initial": {"joints_deg": {"joints": [0]}}}
                },
            }
        )
    )
    return path


async def serve(kind, actions, *, joint=0, fail=False):
    async def status(request):
        return web.json_response(
            {
                "role": "surgeon",
                "session": {
                    "robots": [
                        {
                            "id": "test:arm",
                            "kind": kind,
                            "controls": controls(MiraSimulation({"uri": "unused"}), {})
                            if kind == "mira-sim"
                            else {
                                "cartesian": {"linear_speed_m_s": 0.1},
                                "groups": {"joints": 1},
                                "speed_deg_s": {"max": 20},
                            },
                        }
                    ]
                },
            }
        )

    async def action(request):
        body = await request.json()
        actions.append(body)
        if fail and body["action"] == "robot.move":
            return web.json_response({"error": "Motion fault"}, status=409)
        return web.json_response(
            {"result": {"joints_deg": {"joints": [joint]}, "grippers": {"right": 0}}}
        )

    app = web.Application()
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/action", action)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


@pytest.mark.asyncio
async def test_replay_refuses_physical_robot_before_acquiring(recording):
    actions = []
    runner, url = await serve("franka", actions)
    try:
        with pytest.raises(ValueError, match="matching simulation"):
            await replay.run(recording, [["arm", url, "test:arm"]])
        assert actions == []
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("starting_scene", ["Home", "Reset scene"])
async def test_wrong_start_pose_releases_without_moving(recording, starting_scene):
    manifest = json.loads(recording.read_text())
    manifest["starting_scene"] = starting_scene
    recording.write_text(json.dumps(manifest))
    actions = []
    runner, url = await serve("franka-sim", actions, joint=5)
    try:
        with pytest.raises(ValueError, match=f"Starting joints differ.*use {starting_scene}"):
            await replay.run(recording, [["arm", url, "test:arm"]])
        assert [item["action"] for item in actions] == [
            "robot.acquire",
            "robot.hold",
            "robot.release",
        ]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_keyboard_mapping_and_release_on_completion_or_fault(recording, fail):
    actions = []
    runner, url = await serve("franka-sim", actions, fail=fail)
    try:
        if fail:
            with pytest.raises(ExceptionGroup, match="TaskGroup"):
                await replay.run(recording, [["arm", url, "test:arm"]])
        else:
            await replay.run(recording, [["arm", url, "test:arm"]])
        moves = [item["params"] for item in actions if item["action"] == "robot.move"]
        assert len(moves) == 1
        assert moves[0]["mode"] == "jog"
        assert moves[0]["command"]["translation"] == [1, 0, 0]
        assert moves[0]["speed_deg_s"] == 4
        assert [item["action"] for item in actions[-2:]] == ["robot.hold", "robot.release"]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_checkpoint_runner_skips_redundant_close_and_ignores_timed_deadlines(
    recording, monkeypatch
):
    manifest = json.loads(recording.read_text())
    manifest.update(version=2, environment="mira")
    recording.write_text(json.dumps(manifest))
    with gzip.open(recording.parent / "input.jsonl.gz", "wt") as output:
        output.write(
            json.dumps({"t": 100, "keys": ["n"], "speeds": [20, 50, 40], "grip": {"right": 0}})
            + "\n"
        )

    async def forbidden(*args):
        raise AssertionError("Checkpoint playback must not use wall-clock input deadlines")

    monkeypatch.setattr(replay, "deadline", forbidden)
    actions = []
    runner, url = await serve("mira-sim", actions)
    try:
        await replay.run(recording, [["arm", url, "test:arm"]])
        assert not any(action["action"] == "robot.move" for action in actions)
        assert actions[-1]["action"] == "robot.release"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Robot input expired in transit", "Transport disconnected"])
async def test_checkpoint_cli_recomputes_only_after_known_admission_rejection(message):
    class Client:
        state = {"grippers": {"right": 0.1}}
        attempts = 0
        renewals = 0

        async def send(self, request, inputs):
            if request and request[0] == "grip":
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError(message)
                self.state = {"grippers": {"right": 0}}

        async def action(self, name):
            assert name == "robot.renew"
            self.renewals += 1
            return self.state

    client = Client()
    robot = {"kind": "mira-sim", "controls": controls(MiraSimulation({"uri": "unused"}), {})}
    rows = [{"t": 0, "keys": ["n"], "speeds": [20, 50, 40], "grip": {"right": 0}}]
    if message.startswith("Robot input expired"):
        await replay.play_checkpoints(client, robot, rows, replay.time.monotonic())
        assert client.attempts == 2
        assert client.renewals == 1
    else:
        with pytest.raises(RuntimeError, match=message):
            await replay.play_checkpoints(client, robot, rows, replay.time.monotonic())
        assert client.attempts == 1
        assert client.renewals == 0
