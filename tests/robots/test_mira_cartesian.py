# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tool jogs use measured state, reject IK jumps, and expire without replay."""

import copy
import time

import numpy as np
import pytest
from telesurgery_robots.mira.adapter import Mira, MiraAdapter
from telesurgery_robots.mira.cartesian import SIM_CARTESIAN, bounded_solution, command
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


def test_physical_adapter_provides_tool_feedback_before_first_motion():
    adapter, vendor = MiraAdapter({"uri": "unused"}), Vendor()
    adapter.client.client = vendor
    state = adapter.read()
    assert state["cartesian_mm_deg"]["left"] == [70, 28, -76, 4.6]
    assert {r["method"] for r in vendor.requests} == {"get_mira_pose", "get_mira_fkine_cartesian"}
    assert not state["control_active"]


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


def test_faster_simulated_roll_remains_measured_bounded_and_expires(monkeypatch):
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
    request = {"left": [0, 0, 0, 0, 5], "right": [0] * 5}
    with pytest.raises(ValueError, match="angular step"):
        command(request)  # Physical MIRA retains its one-degree roll limit.
    for _ in range(3):
        robot.apply({"method": "jog_mira_cartesian", "params": request})
        assert robot.pose["left"][4] == 5  # Frozen feedback cannot accumulate roll travel.
    request["left"][4] = 5.01
    with pytest.raises(ValueError, match="angular step"):
        command(request, SIM_CARTESIAN)
    request["left"] = [0, 0, 0, 1.01, 0]
    with pytest.raises(ValueError, match="angular step"):
        command(request, SIM_CARTESIAN)
    clock[0] += 0.21
    assert not robot.apply({"method": "get_state"})["control_active"]
    assert robot.pose["left"][:5] == measured["left"]


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
    # Preserve the previous command while physics catches up.
    robot.apply({"method": "jog_mira_cartesian", "params": movement()})
    assert robot.pose["left"][0] == pytest.approx(MIRA_HOME[0] + 0.2)
    assert robot._state()["cartesian_target_mm_deg"]["left"][0] == pytest.approx(0.2)
    clock[0] += 0.21
    assert not robot.apply({"method": "get_state"})["control_active"]
    assert robot.pose["left"][:5] == measured["left"]
    clock[0] += 0.1
    with pytest.raises(ValueError, match="stale"):
        robot.apply({"method": "jog_mira_cartesian", "params": movement()})


def test_simulator_continuous_tool_travel_survives_servo_lag_and_stops(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    robot = SimRobot()
    measured = {arm: np.array(pose[:5]) for arm, pose in robot.pose.items()}
    start = measured["left"].copy()

    def feedback():
        robot.feedback = {"joints_deg": {arm: q.tolist() for arm, q in measured.items()}}
        robot.kinematics = (
            {
                arm: (q.copy(), q[:4].copy(), np.eye(4), [(-180, 180)] * 4)
                for arm, q in measured.items()
            },
            clock[0],
        )

    # A slow position servo completes only a fraction of each target per frame.
    # 100 fresh 0.1 mm commands must still yield nearly 10 mm, not 2 mm.
    for _ in range(100):
        feedback()
        robot.apply({"method": "jog_mira_cartesian", "params": movement()})
        for arm in measured:
            measured[arm] += 0.2 * (np.array(robot.pose[arm][:5]) - measured[arm])
        clock[0] += 0.05
    assert measured["left"][0] - start[0] == pytest.approx(9.6, abs=0.01)
    feedback()
    robot.apply({"method": "hold"})
    assert robot.pose["left"][:5] == pytest.approx(measured["left"])
    assert not robot._state()["control_active"]

    # Frozen feedback/contact may not accumulate a large deferred target.
    with pytest.raises(ValueError, match="tracking error"):
        for _ in range(20):
            feedback()
            robot.apply({"method": "jog_mira_cartesian", "params": movement()})
            clock[0] += 0.05
    assert robot.pose["left"][:5] == pytest.approx(measured["left"])
    assert not robot._state()["control_active"]


def test_simulator_scales_combined_tool_motion_to_joint_lead_without_losing_direction(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    robot = SimRobot()
    measured = {arm: np.array(pose[:5]) for arm, pose in robot.pose.items()}
    initial = measured["left"].copy()
    # An elbow change needs ten times as much joint travel at this configuration.
    jacobian = np.diag([1.0, 1.0, 1.0, 0.1])
    for _ in range(20):
        robot.feedback = {"joints_deg": {arm: q.tolist() for arm, q in measured.items()}}
        robot.kinematics = (
            {
                arm: (q.copy(), jacobian @ q[:4], jacobian, [(-180, 180)] * 4)
                for arm, q in measured.items()
            },
            clock[0],
        )
        before = np.array(robot.pose["left"][:4])
        robot.apply(
            {
                "method": "jog_mira_cartesian",
                "params": {"left": [0.2, 0, 0, 0.2, 0], "right": [0] * 5},
            }
        )
        target = np.array(robot.pose["left"][:4])
        tool_change = jacobian @ (target - before)
        assert tool_change[0] == pytest.approx(tool_change[3])
        assert np.max(np.abs(target - measured["left"][:4])) <= 1 + 1e-9
        measured["left"][:4] += 0.4 * (target - measured["left"][:4])
        clock[0] += 0.05
    assert measured["left"][3] - initial[3] > 7


@pytest.mark.parametrize("sign", [-1, 1])
def test_simulator_stops_at_joint_limit_and_permits_retreat(sign):
    robot = SimRobot()
    measured = {arm: np.array(pose[:5]) for arm, pose in robot.pose.items()}
    measured["left"][0] = 70 * sign
    robot.feedback = {"joints_deg": {arm: q.tolist() for arm, q in measured.items()}}
    robot.kinematics = (
        {
            arm: (q, q[:4], np.eye(4), [(-70, 70), *[(-180, 180)] * 3])
            for arm, q in measured.items()
        },
        time.monotonic(),
    )
    request = {"left": [0.1 * sign, 0, 0, 0, 0], "right": [0] * 5}
    with pytest.raises(ValueError, match="joint limits"):
        robot.apply({"method": "jog_mira_cartesian", "params": request})
    assert not robot._state()["control_active"]
    request["left"][0] *= -1
    result = robot.apply({"method": "jog_mira_cartesian", "params": request})
    assert result["targets_deg"]["left"][0] == pytest.approx(69.9 * sign)
