# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Completed pickups consent to a release only during a measured receiver replay."""

import copy

import pytest
from telesurgery.controller.replay import Catalog, Rendezvous
from telesurgery.controller.replay_handoff import ReplayHandoff
from telesurgery_core.control.access import Ownership


@pytest.fixture
def handoff():
    now = [0.0]
    owners = {f"node:{role}": Ownership(lambda: now[0]) for role in ("left", "right")}
    barrier = Rendezvous(Catalog(), lambda: now[0])
    contexts, states, calls = {}, {}, []
    for role, device in (("left", "gamepad"), ("right", "haply")):
        key = f"node:{role}"
        run = barrier.join(
            f"versius/{device}",
            {"id": key, "kind": "versius-sim", "simulation": True},
            role,
            owners[key].acquire(role),
        )
        contexts[role] = barrier.handoff(run)
        states[role] = {
            "tool_pose": copy.deepcopy(contexts[role]["pose"]),
            "grippers": {"hand": 0.1},
            "control_active": False,
        }

    async def call(key, method, params):
        if key not in {"node:left", "node:right"}:
            raise RuntimeError("Robot is unavailable")
        role = key.split(":")[-1]
        calls.append((role, method))
        if method == "handoff.acquire":
            token = owners[key].acquire(params["peer"])
            return {"token": token, "state": copy.deepcopy(states[role])}
        if method == "handoff.release":
            owners[key].validate(params["peer"], params["token"])
            owners[key].release()
        if method == "robot.replay_release":
            states[role]["grippers"]["hand"] += 0.2
            return {"done": states[role]["grippers"]["hand"] >= 0.998, "state": states[role]}
        return copy.deepcopy(states[role])

    return ReplayHandoff(owners, call, lambda: now[0]), contexts, states, calls, now


@pytest.mark.asyncio
async def test_completed_left_waits_without_replay_heartbeat_then_releases_after_right_grasp(
    handoff,
):
    helper, contexts, states, calls, now = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    assert not calls
    now[0] = 60
    helper.owners["node:left"].expires = now[0] + 2  # Ordinary control lease remains live.
    await helper.prepare(contexts["right"])
    for _ in range(5):
        done = await helper.update(contexts["right"], states["right"], take=True)
    assert done and not helper.offers
    assert states["left"]["grippers"]["hand"] >= 0.998
    assert states["right"]["grippers"]["hand"] == 0.1
    assert {role for role, _ in calls} == {"left"}
    assert states["left"]["tool_pose"] == contexts["left"]["pose"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition",
    [
        "not_finished",
        "empty_left",
        "manual",
        "expired",
        "new_owner",
        "other_node",
        "other_task",
    ],
)
async def test_right_start_rejects_invalid_donor_presentation(handoff, condition):
    helper, contexts, states, calls, now = handoff
    if condition == "empty_left":
        states["left"]["grippers"]["hand"] = 0
        with pytest.raises(RuntimeError, match="did not retain"):
            await helper.update(contexts["left"], states["left"], finished=True)
    else:
        await helper.update(contexts["left"], states["left"], finished=condition != "not_finished")
    if condition == "manual":
        await helper.clear("node:left")
    elif condition == "expired":
        now[0] = helper.owners["node:left"].expires
    elif condition == "new_owner":
        helper.owners["node:left"].release()
        helper.owners["node:left"].acquire("new surgeon")
    elif condition == "other_node":
        contexts["right"]["key"] = "another-node:right"
    elif condition == "other_task":
        contexts["right"]["group"] = "different-task"
    reason = (
        "Robot is unavailable" if condition == "other_node" else "Left arm must hold the needle"
    )
    with pytest.raises(RuntimeError, match=reason):
        await helper.prepare(contexts["right"])
    assert not any(method == "robot.replay_release" for _, method in calls)


@pytest.mark.asyncio
async def test_manual_receiver_close_does_not_release_completed_pickup(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.prepare(contexts["right"])
    calls.clear()
    await helper.update(contexts["right"], states["right"])
    assert not calls and helper.offers


@pytest.mark.asyncio
async def test_receiver_cancel_holds_partial_release_and_removes_consent(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.prepare(contexts["right"])
    assert not await helper.update(contexts["right"], states["right"], take=True)
    await helper.clear("node:right")
    assert calls[-1] == ("left", "robot.hold")
    assert not helper.offers


@pytest.mark.asyncio
async def test_lost_receiver_grasp_stops_release_and_donor_pose_change_is_rejected(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.prepare(contexts["right"])
    await helper.update(contexts["right"], states["right"], take=True)
    states["right"]["grippers"]["hand"] = 0
    with pytest.raises(RuntimeError, match="right grasp changed"):
        await helper.update(contexts["right"], states["right"], take=True)
    assert calls[-1] == ("left", "robot.hold")


@pytest.mark.asyncio
async def test_release_never_moves_a_donor_that_has_left_the_handoff_pose(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.prepare(contexts["right"])
    states["left"]["tool_pose"]["position_m"][0] += 0.01
    with pytest.raises(RuntimeError, match="left handoff position changed"):
        await helper.update(contexts["right"], states["right"], take=True)
    assert not any(method == "robot.replay_release" for _, method in calls)


@pytest.mark.asyncio
async def test_legacy_or_manual_session_cannot_request_replay_release(handoff):
    helper, _, states, calls, _ = handoff
    with pytest.raises(ValueError, match="does not support"):
        await helper.update(None, states["right"], take=True)
    assert not calls


@pytest.mark.asyncio
async def test_manual_donor_interrupt_cannot_be_mistaken_for_an_empty_pickup(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.prepare(contexts["right"])
    assert not await helper.update(contexts["right"], states["right"], take=True)
    await helper.clear("node:left")
    assert calls[-1] == ("left", "robot.hold")
    with pytest.raises(RuntimeError, match="automatic release was interrupted"):
        await helper.update(contexts["right"], states["right"], take=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_flags", [{}, {"independent_actions": True}])
async def test_old_patient_is_rejected_before_independent_replay_moves(tmp_path, legacy_flags):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from telesurgery.controller.checkpoint_replay import CheckpointPlayback
    from telesurgery.server.application import Application
    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.adapters.simulation import VersiusSimulation

    app = Application("surgeon", tmp_path)
    app.remote_status = {"status": "approved", "robot": True}
    app.tokens["node:left"] = "lease"
    playback = CheckpointPlayback(
        {"kind": "versius-sim", "controls": controls(VersiusSimulation({"uri": "unused"}), {})},
        {"device": "keyboard", "independent_actions": True, "requires_presented_needle": True},
        "left",
        [{"t": 0, "speeds": [20, 50, 40], "grip": {"hand": 0}}],
        "run",
    )
    app.replays["node:left"] = playback
    app.remote = SimpleNamespace(
        call=AsyncMock(
            return_value={
                **legacy_flags,
                "elapsed": 0,
                "done": False,
                "checkpoint": 0,
                "state": {"grippers": {"hand": 1}},
            }
        )
    )
    with pytest.raises(RuntimeError, match="Restart the patient"):
        await app._replay_action("replay.read", {"id": "node:left"})
    assert playback.index == 0 and playback.request is None
    assert [call.args[0] for call in app.remote.call.call_args_list] == [
        "replay.poll",
        "replay.cancel",
    ]


@pytest.mark.asyncio
async def test_empty_receiver_grasp_never_releases_the_donor(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.prepare(contexts["right"])
    states["right"]["grippers"]["hand"] = 0
    with pytest.raises(RuntimeError, match="did not grasp"):
        await helper.update(contexts["right"], states["right"], take=True)
    assert helper.offers
    assert not any(method == "robot.replay_release" for _, method in calls)


@pytest.mark.asyncio
async def test_presented_pickup_stops_if_donor_is_manually_moved_before_grasp(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.prepare(contexts["right"])
    assert contexts["right"]["donor_run"] == contexts["left"]["run"]
    await helper.clear("node:left")
    with pytest.raises(RuntimeError, match="presented needle is no longer available"):
        await helper.update(contexts["right"], states["right"])
    assert not any(method == "robot.replay_release" for _, method in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh", [False, True])
async def test_released_pickup_transfers_after_switch_or_patient_refresh(handoff, refresh):
    helper, contexts, states, calls, now = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    helper.owners["node:left"].release()
    await helper.released("node:left")
    assert helper.offers
    now[0] = 60
    if refresh:
        helper.offers.clear()
        helper.owners.pop("node:left")
    await helper.prepare(contexts["right"])
    assert helper.owners["node:left"].owner is None  # No lease during the approach.
    for _ in range(5):
        done = await helper.update(contexts["right"], states["right"], take=True)
        now[0] += 0.1
    assert done and not helper.offers
    assert states["left"]["grippers"]["hand"] >= 0.998
    assert helper.owners["node:left"].owner is None
    assert calls.count(("left", "handoff.acquire")) == 1
    assert calls[-1] == ("left", "handoff.release")


@pytest.mark.asyncio
async def test_released_donor_cancellation_releases_temporary_control(handoff):
    helper, contexts, states, calls, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    helper.owners["node:left"].release()
    await helper.released("node:left")
    await helper.prepare(contexts["right"])
    assert not await helper.update(contexts["right"], states["right"], take=True)
    await helper.clear("node:right")
    assert helper.owners["node:left"].owner is None
    assert calls[-1] == ("left", "handoff.release")
    assert not helper.offers


@pytest.mark.asyncio
async def test_reset_from_right_invalidates_left_presentation(handoff):
    helper, contexts, states, _, _ = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    await helper.clear_scene("node:right")
    assert not helper.offers


@pytest.mark.asyncio
async def test_recovery_never_takes_another_surgeons_arm(handoff):
    helper, contexts, _, calls, _ = handoff
    with pytest.raises(RuntimeError, match="Left arm must hold"):
        await helper.prepare(contexts["right"])
    assert not calls


@pytest.mark.asyncio
async def test_brief_physics_delay_keeps_donor_closed_until_fresh_feedback(handoff):
    helper, contexts, states, calls, now = handoff
    await helper.update(contexts["left"], states["left"], finished=True)
    helper.owners["node:left"].release()
    await helper.released("node:left")
    await helper.prepare(contexts["right"])
    states["right"]["cartesian_feedback"] = {"ready": False}
    assert not await helper.update(contexts["right"], states["right"], take=True)
    assert not any(method == "robot.replay_release" for _, method in calls)
    now[0] += 0.4
    states["right"]["cartesian_feedback"]["ready"] = True
    assert not await helper.update(contexts["right"], states["right"], take=True)
    assert calls[-1] == ("left", "robot.replay_release")
    await helper.clear("node:right")
