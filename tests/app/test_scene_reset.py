# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared-scene reset requires every other arm to be released and stopped."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telesurgery.server.application import Application
from telesurgery_core.control.access import Ownership


@pytest.fixture
def patient(tmp_path):
    app = Application("patient", tmp_path)

    async def run(function, *args, **kwargs):
        return function(*args)

    app.run = run
    app.node_call = AsyncMock(return_value={"sequence": 1})
    for peer in ("X", "Y"):
        app.access.request(peer, peer, robot=True)
        app.access.approve(peer, robot=True)
    app.nodes["room"] = {
        "status": "online",
        "robots": [
            {
                "id": role,
                "name": role,
                "kind": "versius-sim",
                "simulation": True,
                "controls": {"reset_scene": True},
            }
            for role in ("left", "right", "assistant", "endoscope")
        ],
    }
    app.owners["room:left"] = Ownership()
    app.owners["room:left"].acquire("X")
    return app


def reset_request(patient, sequence=1):
    return {
        "id": "room:left",
        "token": patient.owners["room:left"].token,
        "sequence": sequence,
        "sent_at": time.time(),
        "mode": "reset",
        "command": {},
    }


def left_status(patient):
    return next(r for r in patient.inventory()["robots"] if r["id"] == "room:left")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["right", "assistant", "endoscope"])
@pytest.mark.parametrize("peer", ["X", "Y"])
async def test_scene_reset_rejects_other_arm_owned_even_by_same_surgeon(patient, role, peer):
    # A stale dashboard may still show an enabled icon. Admission checks the
    # current leases, including assistant and endoscope arms, before dispatch.
    assert not left_status(patient)["reset_scene_blocked"]
    run = patient.replay_barrier.join(
        "versius/keyboard", left_status(patient), "X", patient.owners["room:left"].token
    )
    other = patient.owners[f"room:{role}"] = Ownership()
    other.acquire(peer)
    assert "Release control" in left_status(patient)["reset_scene_blocked"]
    with pytest.raises(PermissionError, match="Release control of all other arms"):
        await patient._request(SimpleNamespace(id="X"), "robot.move", reset_request(patient))
    patient.node_call.assert_not_called()
    other.release()
    other.ready = False
    with pytest.raises(PermissionError, match="wait for them to stop"):
        await patient._request(SimpleNamespace(id="X"), "robot.move", reset_request(patient, 2))
    patient.node_call.assert_not_called()
    assert patient.replay_barrier.poll(run, "X", "room:left", patient.owners)["elapsed"] >= 0
    other.ready = True
    assert not left_status(patient)["reset_scene_blocked"]
    await patient._request(SimpleNamespace(id="X"), "robot.move", reset_request(patient, 3))
    assert patient.node_call.await_count == 1
    assert patient.node_call.call_args.args[2]["mode"] == "reset"
    assert patient.owners["room:left"].owner == "X"
    with pytest.raises(RuntimeError, match="Replay stopped"):
        patient.replay_barrier.poll(run, "X", "room:left", patient.owners)


@pytest.mark.asyncio
async def test_reset_still_requires_selected_arm_control_and_ignores_other_scene(patient):
    patient.nodes["other-room"] = patient.nodes["room"]
    patient.owners["other-room:right"] = Ownership()
    patient.owners["other-room:right"].acquire("Y")
    assert not left_status(patient)["reset_scene_blocked"]
    with pytest.raises(PermissionError, match="another surgeon"):
        await patient._request(SimpleNamespace(id="Y"), "robot.move", reset_request(patient))
    patient.node_call.assert_not_called()
    await patient._request(SimpleNamespace(id="X"), "robot.move", reset_request(patient))
    assert patient.node_call.await_count == 1


@pytest.mark.asyncio
async def test_scene_reset_and_other_arm_acquisition_are_serialized(patient):
    resetting, finish = asyncio.Event(), asyncio.Event()

    async def dispatch(node, method, params):
        if method == "robot.move":
            resetting.set()
            await finish.wait()
        return {"sequence": 1}

    patient.node_call.side_effect = dispatch
    reset = asyncio.create_task(
        patient._request(SimpleNamespace(id="X"), "robot.move", reset_request(patient))
    )
    acquire = None
    try:
        await asyncio.wait_for(resetting.wait(), 1)
        acquire = asyncio.create_task(
            patient._request(SimpleNamespace(id="Y"), "robot.acquire", {"id": "room:right"})
        )
        await asyncio.sleep(0)
        assert not acquire.done()
        assert "room:right" not in patient.owners
        finish.set()
        await asyncio.gather(reset, acquire)
        assert patient.owners["room:right"].owner == "Y"
        assert left_status(patient)["reset_scene_blocked"]
    finally:
        finish.set()
        await asyncio.gather(reset, *([acquire] if acquire else []), return_exceptions=True)
