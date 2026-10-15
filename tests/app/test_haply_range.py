# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Measured endpoints, arm switching and calibration must never cause a jump."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from telesurgery.controller.haply import BrowserHaply, Sample, WorkspaceHaply, mapper_for
from telesurgery.controller.haply_range import Range, mapped_position
from telesurgery_robots.mira.cartesian import SIM_CARTESIAN


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


def test_browser_can_calibrate_before_acquiring_control_and_restore_range(monkeypatch, tmp_path):
    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.adapters.simulation import MiraSimulation

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    current = [sample()]
    monkeypatch.setattr("telesurgery.controller.haply.time.monotonic", lambda: 1.0)
    monkeypatch.setattr(
        "telesurgery.controller.haply.Haply",
        lambda: SimpleNamespace(sample=lambda _: (current[0], ""), close=lambda: None),
    )
    robot = {
        "id": "sim",
        "kind": "mira-sim",
        "controls": controls(MiraSimulation({"uri": "unused"}), {}),
    }
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
    restored.close()


@pytest.mark.parametrize("disconnect", [True, False])
def test_interrupted_range_capture_is_cancelled(tmp_path, disconnect):
    calibration = calibrated(tmp_path)
    calibration.action("start", sample())
    calibration.observe(None if disconnect else replace(sample(), generation=2))
    assert not calibration.collecting
    assert calibration.bounds  # The previously saved range remains available.
    with pytest.raises(ValueError, match="Start movement"):
        calibration.action("save", sample())
