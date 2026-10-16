# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remote pose refreshes must not determine servo speed or accumulate stale travel."""

import time

import numpy as np
import pytest
from telesurgery_robots.mira.follow import Follow, command
from telesurgery_robots.simulation.state import SimRobot


class Rig:
    def __init__(self, monkeypatch):
        self.now = 10.0
        monkeypatch.setattr(time, "monotonic", lambda: self.now)
        self.robot = SimRobot()
        self.q = {arm: np.zeros(5) for arm in ("left", "right")}
        self.jacobian = np.diag([10.0, 10.0, 10.0, 1.0])
        self.feedback()

    def feedback(self):
        self.robot.feedback = {
            "joints_deg": {arm: q.tolist() for arm, q in self.q.items()},
            "mira_workspace_mm": {arm: {"min": [-800.0] * 3, "max": [800.0] * 3} for arm in self.q},
        }
        self.robot.kinematics = (
            {
                arm: (q.copy(), self.jacobian @ q[:4], self.jacobian, [(-70.0, 70.0)] * 4)
                for arm, q in self.q.items()
            },
            self.now,
        )

    def send(self, x, arm="left"):
        return self.robot.apply(
            {
                "method": "set_mira_tool_target",
                "params": {
                    "arm": arm,
                    "pose": [x, 0.0, 0.0, 0.0, 0.0],
                    # 50% permits 150 mm/s with this fixture's 10 mm/degree
                    # Jacobian, leaving headroom for the requested 70 mm/s.
                    "arm_percent": 50,
                    "roll_percent": 50,
                    "id": round(self.now * 1000),
                },
            }
        )

    def step(self, dt=0.01, *, frozen=False):
        self.now += dt
        if not frozen:
            for arm in self.q:
                self.q[arm] += 0.4 * (np.array(self.robot.pose[arm][:5]) - self.q[arm])
        self.feedback()
        self.robot.advance()


@pytest.mark.parametrize("interval", [0.05, 0.12])
def test_network_refresh_interval_does_not_throttle_hand_speed(monkeypatch, interval):
    rig = Rig(monkeypatch)
    next_request = rig.now
    start = rig.now
    rig.send(0)
    for _ in range(200):
        if rig.now >= next_request - 1e-8:
            rig.send(70 * (rig.now - start))
            next_request += interval
        rig.step()
    # A 70 mm/s mapped hand motion must remain near 70 mm/s, including
    # 120 ms refreshes that used to restrict default jogging to about 8 mm/s.
    assert 125 < rig.q["left"][0] * 10 < 141
    assert np.max(np.abs(rig.q["right"])) == 0
    assert not rig.robot.mira_follow_error


@pytest.mark.parametrize("sign", [-1, 1])
def test_boundary_stays_active_and_reverse_target_retreats(monkeypatch, sign):
    rig = Rig(monkeypatch)
    rig.q["left"][0] = 69.8 * sign
    rig.feedback()
    for i in range(150):
        if i % 5 == 0:
            rig.send(800 * sign)
        rig.step()
        assert abs(rig.q["left"][0]) <= 70 + 1e-8
    assert rig.robot._state()["mira_follow"]["limited"]
    assert rig.robot._state()["control_active"]
    assert not rig.robot.mira_follow_error
    for i in range(50):
        if i % 5 == 0:
            rig.send(660 * sign)
        rig.step()
    assert rig.q["left"][0] * sign < 67


def test_contact_fault_timeout_and_hold_discard_absolute_target(monkeypatch, caplog):
    rig = Rig(monkeypatch)
    for i in range(100):
        if i % 5 == 0 and not rig.robot.mira_follow_error:
            rig.send(200)
        rig.step(frozen=True)
        assert abs(rig.robot.pose["left"][0]) <= 3 + 1e-8
    assert "tracking error" in rig.robot.mira_follow_error
    assert "left J1" in rig.robot.mira_follow_error
    assert "no joint progress" in rig.robot.mira_follow_error
    faults = [r for r in caplog.records if "tracking error" in r.message]
    assert len(faults) == 1
    assert "commanded_joints_deg=" in faults[0].message
    assert "measured_joints_deg=" in faults[0].message
    assert not rig.robot._state()["control_active"]
    with pytest.raises(ValueError, match="tracking error"):
        rig.send(0)
    rig.robot.apply({"method": "hold"})
    rig.send(50)
    for _ in range(21):
        rig.step()
    assert not rig.robot._state()["control_active"]
    assert rig.robot.mira_follow is None
    assert rig.robot.pose["left"][:5] == pytest.approx(rig.q["left"])


@pytest.mark.parametrize("deflection", [-35.0, 35.0])
def test_roll_contact_does_not_block_tool_retreat(deflection):
    follower = Follow("right", np.zeros(5), 0.0)
    follower.request(
        {
            "pose": [0, 50, 0, 0, -np.sign(deflection) * 20],
            "arm_percent": 50,
            "roll_percent": 50,
        }
    )
    # Contact displaces roll while the operator lifts away. XYZ and roll have
    # separate controls: a blocked roll must not veto the requested retreat.
    measured = np.array([0, 0, 0, 0, deflection], dtype=float)
    jacobian = np.diag([10.0, 10.0, 10.0, 1.0])
    for i in range(1, 51):
        position = follower.advance(
            (measured, jacobian @ measured[:4], jacobian, [(-70, 70)] * 4),
            0.01,
            i * 0.01,
        )
        measured[:4] += 0.4 * (position[:4] - measured[:4])
        assert abs(position[4]) < 1e-8  # No extra pressure into blocked roll.
        assert np.max(np.abs(position[:4] - measured[:4])) <= 3
    assert measured[1] * 10 > 40
    assert not follower.error
    # Sustained obstruction still trips the original no-progress watchdog.
    for i in range(51, 151):
        follower.advance(
            (measured, jacobian @ measured[:4], jacobian, [(-70, 70)] * 4),
            0.01,
            i * 0.01,
        )
    assert "tracking error" in follower.error


def test_external_deflection_allows_reducing_tool_lead():
    follower = Follow("left", [1.6, 0, 0, 0, 0], 0.0)
    follower.request({"pose": [0] * 5, "arm_percent": 20, "roll_percent": 50})
    # Contact displaced the measured tip beyond the 15 mm envelope. A small
    # inward step must be allowed even before it reaches the envelope again.
    measured = np.zeros(5)
    jacobian = np.diag([10.0, 10.0, 10.0, 1.0])
    result = follower.advance((measured, np.zeros(4), jacobian, [(-70, 70)] * 4), 0.01, 0.01)
    assert 1.5 < result[0] < 1.6


@pytest.mark.parametrize(
    "key,value",
    [
        ("pose", [float("nan")] * 5),
        ("arm_percent", 0),
        ("roll_percent", True),
        ("arm", "both"),
        ("arm", []),
        ("id", -1),
    ],
)
def test_follow_contract_rejects_invalid_commands(key, value):
    request = {"arm": "left", "pose": [0.0] * 5, "arm_percent": 20, "roll_percent": 50, "id": 1}
    with pytest.raises(ValueError):
        command({**request, key: value})
