# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Recorded grasp endpoints must survive servo lag and network pacing."""

import copy

import pytest
from telesurgery.controller.checkpoint_replay import CheckpointPlayback, validate_checkpoints
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import MiraSimulation


def player(rows, now):
    robot = {"kind": "mira-sim", "controls": controls(MiraSimulation({"uri": "unused"}), {})}
    return CheckpointPlayback(robot, {"device": "keyboard"}, "mira", rows, "run", lambda: now[0])


def row(**target):
    return {"t": 0, "speeds": [100, 50, 40], "keys": ["y"], **target}


def state(pose):
    return {
        "cartesian_mm_deg": {"right": pose[:4]},
        "cartesian_target_mm_deg": {"right": pose[:4]},
        "joints_deg": {"right": [0, 0, 0, 0, pose[4]]},
        "grippers": {"right": 0},
    }


@pytest.mark.parametrize("delay", [0.05, 0.12, 0.24])
def test_grasp_waits_for_recorded_pose_with_servo_lag_and_packet_delay(delay):
    now = [0.0]
    goal = [8, -12, 4, 2, 10]
    playback = player([row(pose={"right": goal}), row(grip={"right": 0})], now)
    actual = [0.0] * 5
    issued = 0
    for _ in range(400):
        result = playback.read(now[0], state(actual))
        if result["request"]:
            mode, command = result["request"]
            if mode == "release":
                assert actual == pytest.approx(goal, abs=0.15)
                assert playback.index == 1
                break
            assert mode == "cartesian"
            values = command["right"]
            assert sum(v * v for v in values[:3]) <= 25 + 1e-9
            assert max(abs(v) for v in values[3:]) <= 1
            assert command["left"] == [0] * 5
            playback.validate_request(mode, command)
            # An accepted increment only partly becomes measured motion.
            actual = [a + 0.6 * v for a, v in zip(actual, values, strict=True)]
            playback.acknowledge(state(actual))
            issued += 1
        now[0] += delay
    else:
        pytest.fail("Recorded pose was not reached")
    assert issued > 20


def test_planned_arrival_does_not_close_jaws_before_measured_arrival():
    now = [0.0]
    playback = player([row(pose={"right": [1, 0, 0, 0, 0]}), row(grip={"right": 0})], now)
    feedback = state([0, 0, 0, 0, 0])
    feedback["cartesian_target_mm_deg"]["right"][0] = 1
    result = playback.read(0, feedback)
    assert result["request"] is None
    assert playback.index == 0
    for _ in range(21):
        now[0] += 0.25
        if now[0] > 5:
            with pytest.raises(TimeoutError, match="checkpoint"):
                playback.read(now[0], feedback)
        else:
            assert playback.read(now[0], feedback)["request"] is None


def test_opening_slows_near_goal_and_closing_releases_on_stable_contact():
    now = [0.0]
    playback = player([row(grip={"right": 0.25}), row(grip={"right": 0})], now)
    result = playback.read(0, {"grippers": {"right": 0.24}})
    assert result["request"][1]["right"] < 0.2
    playback.acknowledge({})
    now[0] = 0.1
    assert playback.read(0.1, {"grippers": {"right": 0.249}})["request"][0] == "release"
    now[0] += 0.1
    for _ in range(20):
        result = playback.read(now[0], {"grippers": {"right": 0.04}})
        if result["done"]:
            assert result["request"] == ("release", {})
            break
        assert result["request"] == ("grip", {"right": -0.2})
        playback.acknowledge({})
        now[0] += 0.1
    else:
        pytest.fail("Closing input did not release at contact")
    assert now[0] >= 1.4


def test_checkpoints_require_feedback_and_stop_after_polling_stalls():
    now = [0.0]
    playback = player([row(pose={"right": [0] * 5})], now)
    with pytest.raises(ValueError, match="pose feedback"):
        playback.read(0, {})
    now[0] = 0.4
    with pytest.raises(TimeoutError, match="stopped polling"):
        playback.read(0.4, state([0] * 5))


@pytest.mark.parametrize(
    "change",
    [
        {"pose": {"right": [0] * 4}},
        {"pose": {"right": [0, 0, 0, 0, float("nan")]}},
        {"grip": {"right": 1.1}},
        {"hold_s": -1},
        {"hold_s": 1, "grip": {"right": 0}},
    ],
)
def test_invalid_checkpoints_are_rejected_before_playback(change):
    with pytest.raises(ValueError):
        validate_checkpoints([row(**copy.deepcopy(change))])


def test_lift_refreshes_held_close_key_and_releases_after_checkpoint():
    now = [0.0]
    lift = row(pose={"right": [0, 10, 0, 0, 0]})
    lift.update(keys=["i", "n"], squeeze=["right"])
    playback = player([lift], now)
    feedback = state([0] * 5)
    for mode in ["grip", "cartesian", "grip", "cartesian"]:
        result = playback.read(now[0], feedback)
        assert result["request"][0] == mode
        playback.acknowledge(feedback)
        now[0] += 0.06
    result = playback.read(now[0], state([0, 10, 0, 0, 0]))
    assert result["done"]
    assert result["request"] == ("release", {})


def test_checkpoint_grip_refresh_cannot_be_added_without_recorded_close_key():
    checkpoint = row(pose={"right": [0] * 5})
    checkpoint["squeeze"] = ["right"]
    with pytest.raises(ValueError, match="held close key"):
        validate_checkpoints([checkpoint])


def test_display_progress_does_not_reset_between_scheduled_commands():
    now = [0.0]
    end = row(hold_s=1)
    end["t"] = 10
    playback = player([row(pose={"right": [0, 0, 0, 0, 10]}), end], now)
    playback.read(0, state([0] * 5))
    playback.acknowledge({})
    now[0] = 0.06
    halfway = playback.read(now[0], state([0, 0, 0, 0, 5]))
    assert halfway["elapsed"] == 5
    playback.acknowledge({})
    now[0] = 0.07
    between = playback.read(now[0], state([0, 0, 0, 0, 5]))
    assert between["elapsed"] == halfway["elapsed"]
    assert not between["waiting_feedback"]
