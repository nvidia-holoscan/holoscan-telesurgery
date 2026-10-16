# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rate scaling and bounded MIRA motion, without hardware access."""

import pytest
from telesurgery_robots.adapters.base import cartesian_rates
from telesurgery_robots.mira.adapter import Mira
from telesurgery_robots.mira.poses import MIRA_HOME
from telesurgery_robots.mira.velocity import PHYSICAL, JointVelocity


def pose():
    return {arm: [0.0, 60.0, 60.0, 90.0, 0.0, 0.0] for arm in ("left", "right")}


def rates(speed):
    return {"left": [speed, 0, 0, 0, 0], "right": [0.0] * 5}


@pytest.mark.parametrize("fraction", [0.25, 0.5, 1.0])
def test_mira_steady_speed_is_fraction_of_operating_limit(fraction):
    planner, measured = JointVelocity(PHYSICAL), pose()
    requested = 20 * fraction
    planner.request(rates(requested), measured, 0)
    previous = 0
    for tick in range(1, 201):
        now = tick / 100
        if tick % 5 == 0:
            planner.request(rates(requested), measured, now)
        target = planner.advance(measured, now)
        assert abs(target["left"][0] - measured["left"][0]) <= 1
        previous, measured = measured["left"][0], target
    assert (measured["left"][0] - previous) / 0.01 == pytest.approx(requested)


def test_mira_stall_does_not_accumulate_travel_and_expiry_holds():
    planner, measured = JointVelocity(PHYSICAL), pose()
    planner.request(rates(20), measured, 0)
    for tick in range(1, 151):
        now = tick / 100
        if tick % 5 == 0:
            planner.request(rates(20), measured, now)
        target = planner.advance(measured, now)
        assert 0 <= target["left"][0] <= 1
        assert target["right"] == measured["right"]
    assert planner.advance(measured, 1.71) == measured
    assert not planner.active
    assert planner.advance(measured, 1.72) is None


def test_mira_bounds_allow_retreat_from_an_external_out_of_range_pose():
    planner, measured = JointVelocity(PHYSICAL), pose()
    measured["left"][0] = 71
    planner.request(rates(20), measured, 0)
    assert planner.advance(measured, 0.01)["left"][0] == 71
    planner.request(rates(-20), measured, 0.02)
    assert planner.advance(measured, 0.03)["left"][0] < 71


def test_independent_cartesian_rates_keep_a_constant_joint_envelope():
    request = {"translation": [1, 0, 0], "rotation": [0, 0, 1], "rotation_speed_deg_s": 15}
    command, speed = cartesian_rates(request, 4, 20)
    assert speed == 10
    assert command["translation"][0] * 0.1 * speed / 20 == pytest.approx(0.02)
    assert command["rotation"][2] * 30 * speed / 20 == pytest.approx(15)
    idle, idle_speed = cartesian_rates({**request, "rotation": [0, 0, 0]}, 4, 20)
    assert idle_speed == speed
    assert idle["rotation"] == [0, 0, 0]
    assert cartesian_rates({"translation": [1, 0, 0], "rotation": [0, 0, 1]}, 4, 20) == (
        {"translation": [1, 0, 0], "rotation": [0, 0, 1]},
        4,
    )
    for invalid in (True, float("nan"), -1, 31):
        with pytest.raises(ValueError):
            cartesian_rates({**request, "rotation_speed_deg_s": invalid}, 4, 20)


def test_mira_home_requires_near_stable_consecutive_feedback(monkeypatch):
    now = [10.0]
    monkeypatch.setattr("telesurgery_robots.mira.adapter.time.monotonic", lambda: now[0])
    robot = Mira("unused")
    robot.home_target = {arm: [*MIRA_HOME, 0, 0] for arm in ("left", "right")}
    robot.home_deadline = 40
    measured = {arm: [v + 0.5 for v in MIRA_HOME] + [0.5, 0] for arm in ("left", "right")}
    assert robot._feedback(measured)["home_active"]
    now[0] += 0.2
    assert robot._feedback(measured)["home_active"]
    now[0] += 0.5  # A long observation gap must restart the settling interval.
    assert robot._feedback(measured)["home_active"]
    for _ in range(3):
        now[0] += 0.1
        state = robot._feedback(measured)
    assert not state["home_active"]
