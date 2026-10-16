# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Measured endpoints, arm switching and calibration must never cause a jump."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from telesurgery.controller.haply import BrowserHaply, Sample, WorkspaceHaply, mapper_for
from telesurgery.controller.haply_range import Range, mapped_position
from telesurgery.controller.input import Inputs
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import (
    FrankaSimulation,
    MiraSimulation,
    VersiusSimulation,
)
from telesurgery_robots.franka.adapter import Franka
from telesurgery_robots.mira.adapter import MiraAdapter
from telesurgery_robots.mira.cartesian import SIM_CARTESIAN

ROBOTS = ("mira", "mira-sim", "franka", "franka-sim", "versius-sim", "future-robot")


def robot_for(kind):
    adapter = {
        "mira": MiraAdapter,
        "mira-sim": MiraSimulation,
        "franka": Franka,
        "franka-sim": FrankaSimulation,
        "versius-sim": VersiusSimulation,
        "future-robot": FrankaSimulation,
    }[kind]
    return {
        "id": kind,
        "name": kind,
        "kind": kind,
        "status": "online",
        "controls": controls(adapter.__new__(adapter), {"motion_enabled": True}),
        "state": {
            "cartesian_workspace": {
                arm: {"frame": "base", "unit": "m", "min": [-0.1] * 3, "max": [0.1] * 3}
                for arm in ("left", "right", "hand")
            },
            "cartesian_mm_deg": {arm: [0, 0, 0, 25] for arm in ("left", "right")},
            "joints_deg": {arm: [0] * 5 for arm in ("left", "right")},
            "mira_workspace_mm": {
                arm: {"min": [-100] * 3, "max": [100] * 3} for arm in ("left", "right")
            },
            "tool_pose": {
                "position_m": [0, 0, 0],
                "orientation_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            },
        },
    }


def sample(position=(0.0, 0.0, 0.0)):
    return Sample(("base", "grip"), position, (0.0, 0.0, 0.0, 1.0), frozenset(), 1.0)


def calibrated(tmp_path):
    calibration = Range(tmp_path / "range.yaml")
    calibration.action("start", sample())
    calibration.observe(sample((-0.1, -0.1, -0.1)))
    calibration.action("save", sample((0.1, 0.1, 0.1)))
    return calibration


def test_range_persists_and_requires_all_axes_and_same_device_frame(tmp_path):
    calibration = Range(tmp_path / "range.yaml")
    calibration.action("start", sample())
    with pytest.raises(ValueError, match="Sweep"):
        calibration.action("save", sample((0.1, 0.0, 0.0)))
    assert calibration.collecting and not calibration.bounds
    calibration = calibrated(tmp_path)
    restored = Range(calibration.path)
    restored.observe(sample())
    assert restored.bounds == calibration.bounds
    restored.observe(replace(sample(), frame="changed mount"))
    assert restored.bounds is None
    restored.observe(replace(sample(), identity=("different base", "grip")))
    assert restored.bounds is None


@pytest.mark.parametrize("axis", range(3))
@pytest.mark.parametrize("sign", [-1, 1])
def test_calibrated_device_edges_map_to_workspace_edges_without_start_jump(tmp_path, axis, sign):
    bounds = calibrated(tmp_path).bounds
    workspace = {"min": [-200.0, -100.0, -300.0], "max": [400.0, 150.0, 200.0]}
    basis = SIM_CARTESIAN["haply_basis"]
    anchor = (0.02, -0.03, 0.01)
    origin = (50.0, 25.0, -20.0)
    assert mapped_position(anchor, anchor, origin, bounds, workspace, basis) == list(origin)
    position = list(anchor)
    position[axis] = 0.1 * sign
    target = mapped_position(position, anchor, origin, bounds, workspace, basis)
    robot_axis = next(i for i, row in enumerate(basis) if row[axis])
    end = "max" if basis[robot_axis][axis] * sign > 0 else "min"
    assert target[robot_axis] == pytest.approx(workspace[end][robot_axis])
    position[axis] *= 2
    assert mapped_position(position, anchor, origin, bounds, workspace, basis) == target


def test_selected_arm_uses_absolute_target_and_boundary_does_not_pause(tmp_path):
    mapper = WorkspaceHaply(calibrated(tmp_path))
    inputs = SimpleNamespace(
        controls={"mira_cartesian": SIM_CARTESIAN}, arm_percent=20, roll_percent=50
    )
    state = {
        "cartesian_mm_deg": {"left": [10.0, 20.0, 30.0, 25.0], "right": [-10.0, 20.0, 30.0, 25.0]},
        "joints_deg": {"left": [0.0] * 5, "right": [0.0] * 5},
        "mira_workspace_mm": {
            arm: {"min": [-100.0] * 3, "max": [100.0] * 3} for arm in ("left", "right")
        },
    }
    now = 1.0

    def tick(position=(0.0, 0.0, 0.0), buttons=""):
        nonlocal now
        now += 0.05
        return mapper.update(
            replace(sample(position), received=now, buttons=frozenset(buttons)), state, inputs, now
        )

    tick()
    tick(buttons="a")
    tick()
    mode, request = tick((0.01, 0.0, 0.0))
    assert mode == "follow" and request["arm"] == "left"
    assert request["pose"][0] == pytest.approx(-1.0)
    state["mira_follow"] = {"limited": True, "id": request["id"]}
    tick((0.01, 0.0, 0.0))
    assert not mapper.paused
    # One boundary acknowledgement rebases once; reversing the hand retreats.
    assert tick((0.0, 0.0, 0.0))[1]["pose"][0] > state["cartesian_mm_deg"]["left"][0]
    state["mira_follow"] = {}
    tick(buttons="b")
    tick()
    assert tick()[1]["pose"] == [*state["cartesian_mm_deg"]["right"], 0.0]
    assert mapper.arm == "right"
    mapper.calibrate("start", sample())
    assert tick() is None and mapper.paused


def test_only_advertised_simulation_following_uses_workspace_mapping():
    assert isinstance(
        mapper_for({"kind": "mira-sim", "controls": {"mira_follow": {"version": 1}}}),
        WorkspaceHaply,
    )
    assert not isinstance(mapper_for({"kind": "mira-sim", "controls": {}}), WorkspaceHaply)


@pytest.mark.parametrize("kind", ROBOTS)
def test_browser_can_calibrate_before_acquiring_control_and_restore_range(
    monkeypatch, tmp_path, kind
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    current = [sample()]
    monkeypatch.setattr("telesurgery.controller.haply.time.monotonic", lambda: 1.0)
    monkeypatch.setattr(
        "telesurgery.controller.haply.Haply",
        lambda: SimpleNamespace(sample=lambda _: (current[0], ""), close=lambda: None),
    )
    robot = robot_for(kind)
    params = {"token": "preview", "enabled": False}
    browser = BrowserHaply()
    result = browser.read(robot, {**params, "calibration": "start"})
    assert result["paused"] and result["request"] is None
    assert result["calibration"]["collecting"]
    current[0] = sample((-0.1, -0.1, -0.1))
    browser.read(robot, params)
    current[0] = sample((0.1, 0.1, 0.1))
    result = browser.read(robot, {**params, "calibration": "save"})
    assert result["calibration"]["ready"] and not result["calibration"]["collecting"]
    assert result["paused"] and result["request"] is None
    browser.close()
    restored = BrowserHaply()
    assert restored.read(robot, params)["calibration"]["ready"]
    for other in ROBOTS:
        assert restored.read(robot_for(other), params)["calibration"]["ready"]
    restored.close()


@pytest.mark.parametrize("kind", ROBOTS)
def test_all_mappers_require_calibration_and_fresh_centered_start(monkeypatch, tmp_path, kind):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    robot = robot_for(kind)
    mapper = mapper_for(robot)
    inputs = Inputs(robot)
    now = 1.0

    def tick(position=(0, 0, 0), buttons=""):
        nonlocal now
        now += 0.05
        return mapper.update(
            replace(sample(position), received=now, buttons=frozenset(buttons), continuity=0),
            robot["state"],
            inputs,
            now,
        )

    tick()
    tick(buttons="a")
    tick()
    assert mapper.paused and "Calibrate movement range" in mapper.error
    mapper.calibrate("start", sample())
    assert tick((-0.1,) * 3) is None
    assert tick((0.1,) * 3) is None
    mapper.calibrate("save", sample())
    assert mapper.paused
    tick((0.1, 0, 0))
    tick((0.1, 0, 0), "a")
    tick((0.1, 0, 0))
    assert mapper.paused and "Center the pen" in mapper.error
    tick()
    tick(buttons="a")
    assert tick() == ("release", {})
    assert not mapper.paused
    at_start = tick()
    if kind == "mira-sim":
        assert at_start[1]["pose"] == [0, 0, 0, 25, 0]
    else:
        assert at_start is None
    assert tick((0.01, 0, 0))[0] in {"cartesian", "jog", "follow"}
    mapper.calibrate("start", sample())
    assert tick() is None and mapper.paused
    mapper.calibrate("cancel", sample())
    assert tick() is None and mapper.paused  # Saving/cancelling cannot rearm movement.


@pytest.mark.parametrize("kind", ("mira", "franka", "franka-sim", "versius-sim"))
@pytest.mark.parametrize("axis", range(3))
@pytest.mark.parametrize("sign", (-1, 1))
def test_all_jog_mappers_map_full_robot_range_and_allow_retreat(tmp_path, kind, axis, sign):
    import numpy as np
    from telesurgery.controller.haply import DEFAULT_BASIS

    robot = robot_for(kind)
    mapper = mapper_for(robot)
    mapper.calibration = calibrated(tmp_path)
    inputs = Inputs(robot)
    mapper.rebase(sample(), robot["state"])
    hand_edge = np.zeros(3)
    hand_edge[axis] = 0.1 * sign
    target = np.asarray(DEFAULT_BASIS) @ hand_edge
    if kind == "mira":
        robot["state"]["cartesian_mm_deg"]["left"][:3] = (target * 1000).tolist()
    else:
        robot["state"]["tool_pose"]["position_m"] = target.tolist()
    assert mapper.motion(sample(tuple(hand_edge * 2)), robot["state"], inputs, 1.0) is None
    mode, command = mapper.motion(sample(tuple(hand_edge * 0.9)), robot["state"], inputs, 1.1)
    translation = command["left"][:3] if kind == "mira" else command["translation"]
    assert np.dot(translation, target) < 0
    assert mode == ("cartesian" if kind == "mira" else "jog")


@pytest.mark.parametrize("kind", ROBOTS)
def test_native_calibration_collects_without_acquire_or_window_focus(
    monkeypatch, tmp_path, virtual_display, kind
):
    import time
    import tkinter as tk

    from telesurgery.controller.haply import NAME
    from telesurgery.controller.window import Window

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    current = [sample()]
    reader = SimpleNamespace(sample=lambda _: (current[0], ""), close=lambda: None)
    monkeypatch.setattr("telesurgery.controller.window.Gamepads", lambda: None)
    monkeypatch.setattr("telesurgery.controller.window.Haply", lambda: reader)
    monkeypatch.setattr("telesurgery.controller.window.haply_available", lambda: True)
    monkeypatch.setattr(Window, "tick", lambda self: None)
    monkeypatch.setattr(Window, "focused", lambda self: False)
    root = tk.Tk(screenName=virtual_display)
    client = SimpleNamespace(action=Mock(side_effect=AssertionError("No robot commands")))
    window = Window(root, client, input_device={"name": NAME, "ordinal": 0, "count": 1})
    try:
        now = time.monotonic()
        window.update_status(
            {
                "role": "surgeon",
                "session": {
                    "id": "me",
                    "status": "approved",
                    "robot": True,
                    "robots": [robot_for(kind)],
                },
            },
            now,
        )
        window.poll_devices(now)
        window.feedback()
        root.update()
        assert window.range_button.winfo_ismapped()
        window.calibrate_haply("start")
        current[0] = sample((-0.1,) * 3)
        window.drive(now)
        current[0] = sample((0.1,) * 3)
        window.drive(now)
        window.feedback()
        assert "200 / 200 / 200" in window.range_hint.cget("text")
        assert window.range_button.cget("text") == "Save range"
        window.calibrate_haply("save")
        assert window.haply_input.calibration.status()["ready"]
        assert window.haply_input.paused and window.control.owned is None
        client.action.assert_not_called()
    finally:
        window.shutdown()
        root.destroy()


@pytest.mark.parametrize("disconnect", [True, False])
def test_interrupted_range_capture_is_cancelled(tmp_path, disconnect):
    calibration = calibrated(tmp_path)
    calibration.action("start", sample())
    calibration.observe(None if disconnect else replace(sample(), generation=2))
    assert not calibration.collecting
    assert calibration.bounds  # The previously saved range remains available.
    with pytest.raises(ValueError, match="Start movement"):
        calibration.action("save", sample())
