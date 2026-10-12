# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tool jogs use measured state, reject IK jumps, and expire without replay."""

import copy
import time

import numpy as np
import pytest
from telesurgery_robots.mira.adapter import Mira
from telesurgery_robots.mira.cartesian import bounded_solution, command
from telesurgery_robots.mira.poses import MIRA_HOME
from telesurgery_robots.simulation.state import SimRobot


def movement():
    return {"left": [0.1, 0, 0, 0, 0], "right": [0] * 5}


class Vendor:
    def __init__(self):
        self.pose = {arm: [*MIRA_HOME, 12, 345] for arm in ("left", "right")}
        self.requests = []
        self.jump = False

    def send(self, request):
        self.requests.append(copy.deepcopy(request))
        method = request["method"]
        if method == "get_mira_pose":
            return copy.deepcopy(self.pose)
        if method == "get_mira_fkine_cartesian":
            return {"left": [70, 28, -76, 4.6], "right": [70, -28, -76, 4.6]}
        if method == "get_mira_cartesian_ik":
            pose = copy.deepcopy(self.pose)
            pose["left"][0] += 10 if self.jump else 0.1
            pose["right"][0] += 20  # An idle arm's unrelated IK branch must be ignored.
            return pose
        raise AssertionError(method)

    def notify(self, request):
        self.requests.append(copy.deepcopy(request))

    def close(self):
        pass


def test_vendor_cartesian_queries_bound_both_arms_and_expire(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    mira, vendor = Mira("unused"), Vendor()
    mira.client = vendor
    mira.send({"method": "jog_mira_cartesian", "params": movement()})
    queries = [r for r in vendor.requests if r["method"] == "get_mira_cartesian_ik"]
    assert queries[0]["params"]["left"] == [70.1, 28, -76, 4.6]
    sent = [r for r in vendor.requests if r["method"] == "set_mira_pose"]
    assert sent[-1]["params"]["left"][0] == pytest.approx(MIRA_HOME[0] + 0.1)
    assert sent[-1]["params"]["left"][4:] == [12, 345]
    assert sent[-1]["params"]["right"] == vendor.pose["right"]
    clock[0] += 0.21
    state = mira.state()
    assert not state["control_active"]
    assert not state["hardware_timestamp_available"]
    assert not state["stop_acknowledged"]
    assert [r for r in vendor.requests if r["method"] == "set_mira_pose"][-1][
        "params"
    ] == vendor.pose
    vendor.jump = True
    count = len([r for r in vendor.requests if r["method"] == "set_mira_pose"])
    with pytest.raises(ValueError, match="joint-step"):
        mira.send({"method": "jog_mira_cartesian", "params": movement()})
    assert len([r for r in vendor.requests if r["method"] == "set_mira_pose"]) == count


@pytest.mark.parametrize("bad", [[0.5, 0.5, 0, 0, 0], [0, 0, 0, 2, 0], [float("nan")] * 5])
def test_tool_input_rejects_unbounded_or_nonfinite_values(bad):
    with pytest.raises(ValueError):
        command({"left": bad, "right": [0] * 5})


def test_ik_rejects_invalid_second_arm_before_motion():
    pose = Vendor().pose
    with pytest.raises(ValueError):
        bounded_solution({"left": pose["left"], "right": [0]}, pose, movement())


def test_simulator_uses_physics_jacobian_and_measured_hold(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    robot = SimRobot()
    measured = {arm: [*MIRA_HOME, 0] for arm in robot.pose}
    robot.feedback = {"joints_deg": measured}
    robot.kinematics = (
        {
            arm: (np.array(q), np.zeros(4), np.eye(4), [(-180, 180)] * 4)
            for arm, q in measured.items()
        },
        clock[0],
    )
    result = robot.apply({"method": "jog_mira_cartesian", "params": movement()})
    assert result["control_active"]
    assert result["targets_deg"]["left"][0] == pytest.approx(MIRA_HOME[0] + 0.1)
    # Repeated requests do not accumulate a target ahead of measured physics.
    robot.apply({"method": "jog_mira_cartesian", "params": movement()})
    assert robot.pose["left"][0] == pytest.approx(MIRA_HOME[0] + 0.1)
    clock[0] += 0.21
    assert not robot.apply({"method": "get_state"})["control_active"]
    assert robot.pose["left"][:5] == measured["left"]
    clock[0] += 0.1
    with pytest.raises(ValueError, match="stale"):
        robot.apply({"method": "jog_mira_cartesian", "params": movement()})
