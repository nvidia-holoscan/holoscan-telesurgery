# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Feedback gates remote replay; elapsed network time cannot increase grip travel."""

import pytest
from telesurgery.controller.replay import FeedbackPlayback
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import MiraSimulation


def playback(rows, now):
    robot = {"kind": "mira-sim", "controls": controls(MiraSimulation({"uri": "unused"}), {})}
    return FeedbackPlayback(robot, {"device": "keyboard"}, "mira", rows, "run", lambda: now[0])


def row(t, keys):
    return {"t": t, "keys": keys, "speeds": [20, 50, 40]}


def state(value):
    return {
        "joints_deg": {arm: [value] * 5 for arm in ("left", "right")},
        "targets_deg": {arm: [1] * 6 for arm in ("left", "right")},
    }


def test_joint_feedback_paces_replay_after_network_delay():
    now = [0.0]
    replay = playback([row(0, ["w"]), row(0.05, ["s"]), row(0.1, [])], now)
    assert replay.read(0, state(0))["request"][0] == "cartesian"
    replay.acknowledge(state(0))
    for i in range(1, 5):
        now[0] = i * 0.25
        result = replay.read(now[0], state(0))
        assert result["request"] is None
        assert result["waiting_feedback"]
        assert replay.index == 1
    now[0] += 0.2
    assert replay.read(now[0], state(1))["request"][0] == "cartesian"
    assert replay.index == 2


def test_motion_timeout_and_missing_measured_feedback_do_not_advance():
    now = [0.0]
    replay = playback([row(0, ["w"])], now)
    replay.read(0, state(0))
    replay.acknowledge(state(0))
    with pytest.raises(ValueError, match="measured joint"):
        replay.read(0, {"targets_deg": state(0)["targets_deg"]})
    now[0] = 5.1
    replay.read_at = now[0]  # A live dashboard cannot renew a blocked motion forever.
    with pytest.raises(TimeoutError, match="did not reach"):
        replay.read(now[0], state(0))
    assert not replay.finished


def test_grip_goal_uses_recorded_duration_and_stops_on_measured_arrival():
    now = [0.0]
    replay = playback([row(0, ["x"]), row(0.5, ["x"]), row(1, []), row(1.1, ["w"])], now)
    initial = {"grippers": {"left": 0.1, "right": 0}}
    assert replay.read(0, initial)["request"][0] == "grip"
    assert replay.index == 2  # Coalesce repeats, preserving the release edge.
    assert replay.pending["goals"] == pytest.approx({"left": 0.3})
    replay.acknowledge(initial)
    for i in range(1, 10):
        now[0] = i * 0.2
        assert replay.read(now[0], initial)["request"][0] == "grip"
        assert replay.pending["goals"] == pytest.approx({"left": 0.3})
    now[0] += 0.2
    assert replay.read(now[0], {"grippers": {"left": 0.3}})["request"][0] == "release"
    assert replay.pending is None
    assert not replay.finished


def test_grip_key_transition_is_not_coalesced_or_treated_as_reached():
    now = [0.0]
    replay = playback([row(0, ["x"]), row(0.5, ["z"]), row(1, [])], now)
    replay.read(0, {"grippers": {"left": 0.1}})
    assert replay.index == 1
    assert replay.pending["goals"]["left"] == pytest.approx(0.2)
    assert not replay.finished


def test_continuous_input_keeps_recorded_cadence_without_waiting_for_each_step_to_settle():
    now = [0.0]
    rows = [row(i * 0.05, ["t"]) for i in range(100)] + [row(5, [])]
    replay = playback(rows, now)
    issued = []
    # Normal servo following error exceeds the settle tolerance but stays
    # inside the controller's one-degree lead envelope. Include 10 ms polling
    # jitter; it must not add another delay to every recorded sample.
    for tick in range(501):
        now[0] = tick * 0.01
        result = replay.read(now[0], state(0.4))
        if result["request"]:
            issued.append(now[0])
            replay.acknowledge(state(0.4))
    assert len(issued) == 100
    assert issued[-1] == pytest.approx(4.95, abs=0.011)
    assert replay.index == 100  # The release still waits for measured arrival.
    now[0] += 0.01
    assert replay.read(now[0], state(1))["request"] == ("release", {})
    assert replay.finished


def test_continuous_input_pauses_for_tracking_lag_without_a_catchup_burst():
    now = [0.0]
    replay = playback([row(i * 0.05, ["w"]) for i in range(20)], now)
    replay.read(0, state(0))
    replay.acknowledge(state(0))
    for tick in range(1, 11):
        now[0] = tick * 0.1
        result = replay.read(now[0], state(-1))
        assert result["request"] is None
        assert result["waiting_feedback"]
    now[0] += 0.05
    assert replay.read(now[0], state(1))["request"]
    replay.acknowledge(state(1))
    assert replay.index == 2
    for _ in range(1, 4):
        now[0] += 0.01
        assert replay.read(now[0], state(1))["request"] is None
    assert replay.index == 2


def test_closing_jaw_can_stop_at_contact_after_recorded_squeeze():
    now = [0.0]
    replay = playback([row(0, ["z"]), row(1, []), row(1.1, ["w"])], now)
    initial = {"grippers": {"left": 0.1}}
    replay.read(0, initial)
    replay.acknowledge(initial)
    for tick in range(1, 10):
        now[0] = tick * 0.1
        result = replay.read(now[0], {"grippers": {"left": 0.02}})
        assert result["request"][0] == "grip"
    now[0] = 1.01
    result = replay.read(now[0], {"grippers": {"left": 0.02}})
    assert result["request"] == ("release", {})
    assert not replay.finished  # Contact does not mark the task complete.


def test_blocked_opening_gripper_still_times_out():
    now = [0.0]
    replay = playback([row(0, ["x"]), row(1, [])], now)
    initial = {"grippers": {"left": 0.1}}
    replay.read(0, initial)
    replay.acknowledge(initial)
    for tick in range(1, 31):
        now[0] = tick * 0.2
        replay.read(now[0], initial)
    now[0] = 6.1
    with pytest.raises(TimeoutError, match="did not reach"):
        replay.read(now[0], initial)


def test_small_gripper_opening_is_not_shortened_by_a_large_absolute_tolerance():
    now = [0.0]
    rows = [
        {"t": 0, "keys": ["x"], "speeds": [20, 50, 5]},
        {"t": 1.55, "keys": [], "speeds": [20, 50, 5]},
    ]
    replay = playback(rows, now)
    initial = {"grippers": {"left": 0}}
    replay.read(0, initial)
    replay.acknowledge(initial)
    assert replay.read(0, {"grippers": {"left": 0.029}})["request"][0] == "grip"
    assert replay.read(0, {"grippers": {"left": 0.037}})["request"] == ("release", {})
