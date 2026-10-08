# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

import pytest
from telesurgery_robots.mira.gripper import GripperJog, gripper_rates


@pytest.mark.parametrize("interval", [0.02, 0.05, 0.1])
def test_gripper_speed_both_arms_and_release(monkeypatch, interval):
    clock = [0.0]
    monkeypatch.setattr(
        "telesurgery_robots.mira.gripper.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    jog = GripperJog()
    measured = {"left": 0.1, "right": 0.9}
    for _ in range(round(1 / interval)):
        jog.command({"left": 0.2, "right": -0.2}, measured)
        clock[0] += interval
        measured.update(jog.advance(measured))
    assert measured == pytest.approx({"left": 0.3, "right": 0.7})
    assert jog.stop(measured) == measured
    clock[0] += 1
    assert jog.advance(measured) == {}


def test_gripper_watchdog_does_not_accumulate_behind_stalled_tool(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(
        "telesurgery_robots.mira.gripper.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    jog = GripperJog()
    measured = {"left": 0.3}
    for _ in range(40):
        jog.command({"left": 0.2}, measured)
        clock[0] += 0.05
        targets = jog.advance(measured)
        assert not targets or targets["left"] <= 0.32
    clock[0] += 0.3
    assert jog.advance(measured) == measured
    assert not jog.rates
    clock[0] += 1
    assert not jog.advance(measured)


@pytest.mark.parametrize(
    "command",
    [
        {"left": 1},
        {},
        {"velocity": {}},
        {"velocity": {"left": True}},
        {"velocity": {"left": float("nan")}},
        {"velocity": {"left": 0.6}},
        {"velocity": {"other": 0.2}},
    ],
)
def test_gripper_rejects_old_absolute_commands_and_invalid_rates(command):
    with pytest.raises(ValueError):
        gripper_rates(command, ("left", "right"))


def test_idle_arm_is_not_commanded_when_only_other_gripper_moves(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(
        "telesurgery_robots.mira.gripper.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    jog = GripperJog()
    measured = {"left": 0.3, "right": 1.0}
    jog.command({"left": 0.2, "right": 0}, measured)
    clock[0] += 0.05
    assert set(jog.advance(measured)) == {"left"}
    jog.command({"left": 0, "right": 0.2}, measured)
    clock[0] += 0.05
    targets = jog.advance(measured)
    assert targets["left"] == measured["left"]
    assert "left" not in jog.rates
