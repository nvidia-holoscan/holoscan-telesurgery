# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Recorded input uses normal mappings and releases ownership when replay fails."""

import gzip
import importlib.util
import json
from pathlib import Path

import pytest
from aiohttp import web

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
                            "controls": {
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
        return web.json_response({"result": {"joints_deg": {"joints": [joint]}}})

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
async def test_wrong_start_pose_releases_without_moving(recording):
    actions = []
    runner, url = await serve("franka-sim", actions, joint=5)
    try:
        with pytest.raises(ValueError, match="starting joints differ"):
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
