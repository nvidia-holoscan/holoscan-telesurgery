# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cartesian requests use measured kinematics and expire on the simulation node."""

import time

import numpy as np
import pytest
from telesurgery_robots.adapters.base import cartesian_command
from telesurgery_robots.franka.cartesian import JOINT_LIMITS, CartesianTrajectory, joint_velocity
from telesurgery_robots.simulation.state import SimRobot


@pytest.mark.parametrize("index", range(6))
def test_cartesian_axes_follow_jacobian_and_joint_speed_limit(index):
    request = np.zeros(6)
    request[index] = 1
    jacobian = np.eye(6, 7)
    position = JOINT_LIMITS.mean(axis=1)
    velocity = np.array(joint_velocity(jacobian, position, request[:3], request[3:], 4))
    assert velocity[index] > 0
    assert np.max(np.abs(velocity)) <= 4
    assert np.count_nonzero(velocity) == 1
    assert np.sign((jacobian @ velocity)[index]) == 1
    negative = joint_velocity(jacobian, position, -request[:3], -request[3:], 4)
    np.testing.assert_allclose(negative, -velocity)


def test_singular_and_near_limit_solutions_remain_bounded():
    position = JOINT_LIMITS.mean(axis=1)
    for jacobian in [np.zeros((6, 7)), np.full((6, 7), 1e-9)]:
        velocity = joint_velocity(jacobian, position, [1, 1, 1], [1, 1, 1], 4)
        assert np.isfinite(velocity).all()
        assert max(map(abs, velocity)) <= 4
    position[0] = JOINT_LIMITS[0, 1]
    assert joint_velocity(np.eye(6, 7), position, [1, 0, 0], [0, 0, 0], 4) == [0] * 7


@pytest.mark.parametrize("direction", [-1, 1])
def test_redundant_joint_can_continue_when_another_reaches_its_limit(direction):
    jacobian = np.eye(6, 7)
    jacobian[0, 6] = 1
    position = JOINT_LIMITS.mean(axis=1)
    position[0] = JOINT_LIMITS[0, int(direction > 0)]
    velocity = np.array(joint_velocity(jacobian, position, [direction, 0, 0], [0, 0, 0], 4))
    assert velocity[0] == pytest.approx(0)
    assert velocity[6] * direction > 1
    assert np.max(np.abs(velocity)) <= 4
    assert np.linalg.norm((jacobian @ velocity)[1:]) < 1e-8
    # Reversal can use the first joint again immediately.
    reverse = joint_velocity(jacobian, position, [-direction, 0, 0], [0, 0, 0], 4)
    assert reverse[0] * direction < 0


@pytest.mark.parametrize(
    "command",
    [
        {"translation": [float("nan"), 0, 0], "rotation": [0, 0, 0]},
        {"translation": [2, 0, 0], "rotation": [0, 0, 0]},
        {"translation": [0, 0], "rotation": [0, 0, 0]},
        {"translation": [True, 0, 0], "rotation": [0, 0, 0]},
        {"translation": [0, 0, 0]},
        {"translation": [0, 0, 0], "rotation": [0, 0, 0], "joints": [0] * 7},
    ],
)
def test_invalid_cartesian_request_is_rejected(command):
    with pytest.raises(ValueError):
        cartesian_command(command)


def test_node_watchdog_stale_feedback_stop_and_mode_guards(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    robot = SimRobot("franka")
    request = {
        "method": "set_cartesian_velocity",
        "params": {
            "translation": [1, 0, 0],
            "rotation": [0, 0, 0],
            "speed_deg_s": 4,
        },
    }
    with pytest.raises(ValueError, match="feedback"):
        robot.apply(request)
    assert robot._state()["cartesian_feedback"] == {"ready": False, "age_ms": None}
    robot.kinematics = (np.array(robot.pose["joints"]), np.eye(6, 7), now[0] - 1)
    with pytest.raises(ValueError, match="feedback"):
        robot.apply(request)
    assert robot._state()["cartesian_feedback"] == {"ready": False, "age_ms": 1000}

    def tick():
        now[0] += 0.02
        robot.kinematics = (np.array(robot.pose["joints"]), np.eye(6, 7), now[0])
        robot.advance()

    tick()
    assert robot._state()["cartesian_feedback"] == {"ready": True, "age_ms": 0}
    start = robot.pose["joints"][0]
    for _ in range(50):
        robot.apply(request)
        tick()
    assert robot.pose["joints"][0] > start + 0.5
    # Drives receive the planned velocity as well as position, including the
    # smooth stop. It must disappear when the trajectory finishes.
    assert 0 < robot.joint_target_velocity[0] <= 4
    with pytest.raises(ValueError, match="Cartesian"):
        robot.apply({"method": "set_home"})
    with pytest.raises(ValueError, match="speed"):
        robot.apply({**request, "params": {**request["params"], "speed_deg_s": 8}})
    # No more input: the local 500 ms deadline begins a smooth stop.
    for _ in range(100):
        tick()
    assert robot.cartesian is None
    assert robot.joint_target_velocity == [0.0] * 7
    stopped = list(robot.pose["joints"])
    for _ in range(10):
        tick()
    assert robot.pose["joints"] == stopped
    # Explicit stop and stale feedback also retire a held command.
    for reason in ("hold", "stale", "missing"):
        robot.apply(request)
        tick()
        if reason == "hold":
            robot.apply({"method": "hold"})
        else:
            robot.kinematics = None if reason == "missing" else (*robot.kinematics[:2], now[0] - 1)
            now[0] += 0.02
            robot.advance()
        assert robot.cartesian.stopping
        if reason == "hold":
            deadline = robot.cartesian.deadline
            assert robot.apply(request)["stopping"]
            assert robot.cartesian.deadline == deadline
        else:
            with pytest.raises(ValueError, match="stale"):
                robot.apply(request)
        for _ in range(100):
            tick()
        assert robot.cartesian is None


def test_fixed_tool_does_not_accept_gripper_commands():
    robot = SimRobot("franka")
    robot.gripper_ranges = {}
    assert not robot.apply({"method": "get_state"})["gripper_available"]
    with pytest.raises(ValueError, match="Unknown gripper"):
        robot.apply({"method": "jog_gripper", "params": {"velocity": {"hand": 0.2}}})


def test_cartesian_enable_preserves_loaded_drive_target(monkeypatch):
    monkeypatch.setattr("time.monotonic", lambda: 100)
    robot = SimRobot("franka")
    target = list(robot.pose["joints"])
    measured = np.array(target) + 0.8
    robot.kinematics = (measured, np.eye(6, 7), 100)
    robot.apply(
        {
            "method": "set_cartesian_velocity",
            "params": {
                "translation": [1, 0, 0],
                "rotation": [0, 0, 0],
                "speed_deg_s": 4,
            },
        }
    )
    assert robot.cartesian.input.current_position == target


def test_coordinated_ramps_preserve_tool_direction_and_excessive_tracking_error_stops():
    position = JOINT_LIMITS.mean(axis=1)
    trajectory = CartesianTrajectory(position, 20)
    # A coupled Jacobian needs unequal joint velocities to move in X alone.
    jacobian = np.eye(6, 7)
    jacobian[:2, :2] = [[1, 1], [1, -2]]
    start = position.copy()
    command = {"translation": [1, 0, 0], "rotation": [0, 0, 0]}
    for tick in range(100):
        now = tick * 0.01
        trajectory.request(command, now)
        position = trajectory.advance(position, jacobian, 0.01, now)
        displacement = jacobian @ np.deg2rad(np.array(position) - start)
        assert abs(displacement[1]) < 0.001
        assert displacement[0] >= 0
    assert displacement[0] > 0.03
    trajectory.advance(np.array(position) + 20, jacobian, 0.01, now)
    assert trajectory.stopping and trajectory.stop_reason == "joint tracking error"


def test_full_speed_release_brakes_within_half_second():
    position = JOINT_LIMITS.mean(axis=1)
    trajectory = CartesianTrajectory(position, 20)
    jacobian = np.eye(6, 7)
    command = {"translation": [0, 0, 0], "rotation": [0, 0, 1]}
    for tick in range(100):
        now = tick * 0.01
        trajectory.request(command, now)
        position = trajectory.advance(position, jacobian, 0.01, now)
    assert trajectory.input.current_velocity[5] == pytest.approx(20)
    trajectory.stop()
    start = np.array(position)
    for tick in range(50):
        position = trajectory.advance(position, jacobian, 0.01, now + (tick + 1) * 0.01)
        assert 0 <= trajectory.input.current_velocity[5] <= 20
    assert trajectory.finished
    assert 0 < position[5] - start[5] < 5


@pytest.mark.parametrize("direction", [-1, 1])
def test_full_speed_limit_approach_and_reversal(direction):
    position = JOINT_LIMITS.mean(axis=1)
    position[5] = JOINT_LIMITS[5, int(direction > 0)] - direction * 20
    trajectory = CartesianTrajectory(position, 20)
    jacobian = np.eye(6, 7)
    command = {"translation": [0, 0, 0], "rotation": [0, 0, direction]}
    peak_speed = 0
    for tick in range(1000):
        now = tick * 0.01
        trajectory.request(command, now)
        position = trajectory.advance(position, jacobian, 0.01, now)
        planned = np.array(trajectory.input.current_position)
        assert np.all(planned >= JOINT_LIMITS[:, 0])
        assert np.all(planned <= JOINT_LIMITS[:, 1])
        np.testing.assert_allclose(position, planned)
        peak_speed = max(peak_speed, abs(trajectory.input.current_velocity[5]))
    assert peak_speed == pytest.approx(20)
    assert abs(trajectory.input.current_velocity[5]) < 0.001
    stopped = position[5]
    command["rotation"][2] = -direction
    for tick in range(50):
        now = 10 + tick * 0.01
        trajectory.request(command, now)
        position = trajectory.advance(position, jacobian, 0.01, now)
    assert (stopped - position[5]) * direction > 1
    assert not trajectory.stopping


def test_cartesian_refresh_tolerates_jitter_but_expires_missing_input():
    position = JOINT_LIMITS.mean(axis=1)
    trajectory = CartesianTrajectory(position, 4)
    jacobian = np.eye(6, 7)
    command = {"translation": [1, 0, 0], "rotation": [0, 0, 0]}
    for tick in range(100):
        now = tick * 0.01
        if tick % 40 == 0:
            trajectory.request(command, now)
        position = trajectory.advance(position, jacobian, 0.01, now)
        assert not trajectory.stopping
    # No fresh input after t=.80: timeout starts braking at t>1.30.
    position = trajectory.advance(position, jacobian, 0.1, 1.20)
    assert not trajectory.stopping
    trajectory.advance(position, jacobian, 0.1, 1.31)
    assert trajectory.stopping and trajectory.stop_reason == "input expired"


def test_cartesian_adapter_enforces_capability_lease_sequence_and_command_age():
    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.adapters.simulation import FrankaSimulation
    from telesurgery_robots.franka.adapter import Franka
    from telesurgery_runtime.application.robots import Controller

    sim = SimRobot("franka")
    sim.gripper_ranges = {}
    sim.kinematics = (np.array(sim.pose["joints"]), np.eye(6, 7), time.monotonic())
    adapter = FrankaSimulation({"uri": "unused"})
    adapter.request = lambda method, params=None: sim.apply({"method": method, "params": params})
    controller = Controller(adapter, lambda: {}, lambda: 0)
    command = {"translation": [1, 0, 0], "rotation": [0, 0, 0]}
    with pytest.raises(PermissionError):
        controller.move("owner", 1, command, time.time(), speed_deg_s=4)
    controller.prepare("owner")
    assert controls(adapter, {})["cartesian"]["frame"] == "base"
    assert "grippers" not in controls(adapter, {})
    with pytest.raises(ValueError, match="expired"):
        controller.move("owner", 1, command, time.time() - 1, speed_deg_s=4)
    with pytest.raises(ValueError, match="Cartesian"):
        controller.move("owner", 1, command, time.time(), mode="step", speed_deg_s=4)
    result = controller.move("owner", 1, command, time.time(), speed_deg_s=4)
    assert result["control_active"]
    with pytest.raises(ValueError, match="Stale"):
        controller.move("owner", 1, command, time.time(), speed_deg_s=4)
    controller.release("owner")
    assert sim.cartesian.stopping
    # Physical hardware advertises the same tool controls, with its own native loop.
    from types import SimpleNamespace

    physical = Franka.__new__(Franka)
    physical.read = lambda: {}
    moves = []
    physical.reader = SimpleNamespace(
        jog_cartesian=lambda command, **kw: moves.append((command, kw)), hold=lambda: None
    )
    controller = Controller(physical, lambda: {"motion_enabled": True}, lambda: 0)
    controller.prepare("owner")
    assert controls(physical, {"motion_enabled": True})["cartesian"]["frame"] == "base"
    assert "cartesian" not in controls(physical, {"motion_enabled": False})
    with pytest.raises(ValueError, match="Cartesian"):
        controller.move("owner", 1, command, time.time(), mode="step", speed_deg_s=4)
    with pytest.raises(ValueError, match="expired"):
        controller.move("owner", 1, command, time.time() - 1, speed_deg_s=4)
    controller.move("owner", 1, command, time.time(), speed_deg_s=4)
    assert moves == [([1, 0, 0, 0, 0, 0], {"speed": pytest.approx(np.deg2rad(4))})]
    with pytest.raises(ValueError, match="Stale"):
        controller.move("owner", 1, command, time.time(), speed_deg_s=4)
    controller.release("owner")
    with pytest.raises(PermissionError):
        controller.move("owner", 2, command, time.time(), speed_deg_s=4)


@pytest.mark.parametrize("environment", ["franka", "versius"])
def test_blocked_motion_holds_measured_pose_and_can_retreat(environment):
    sim = SimRobot(environment)
    position = np.array(sim.pose["joints"])
    jacobian = np.eye(6, len(position))
    sim.kinematics = position, jacobian, time.monotonic()
    command = {"translation": [1, 0, 0], "rotation": [0, 0, 0], "speed_deg_s": 4}
    sim.apply({"method": "set_cartesian_velocity", "params": command})
    blocked = position.copy()
    blocked[0] -= 5  # More than the bounded drive tracking allowance.
    for _ in range(30):
        now = sim.updated + 0.02
        sim.kinematics = blocked, jacobian, now
        sim.advance(now)
        if sim.cartesian is None:
            break
    assert sim.cartesian is None
    np.testing.assert_allclose(sim.pose["joints"], blocked)
    sim.kinematics = blocked, jacobian, time.monotonic()
    sim.apply(
        {"method": "set_cartesian_velocity", "params": {**command, "translation": [-1, 0, 0]}}
    )
    now = sim.updated + 0.02
    sim.kinematics = blocked, jacobian, now
    sim.advance(now)
    assert sim.cartesian is not None and not sim.cartesian.stopping
    assert sim.pose["joints"][0] < blocked[0]


@pytest.mark.parametrize("environment", ["franka", "versius"])
@pytest.mark.parametrize("finish", ["complete", "stop", "timeout"])
def test_home_restores_gripper_and_waits_for_measured_opening(environment, finish, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    sim = SimRobot(environment)
    sim.feedback = {"grippers": {"hand": 0.35}}
    sim.finger_target = 0.014
    sim.apply({"method": "jog_gripper", "params": {"velocity": {"hand": -0.2}}})
    state = sim.apply({"method": "set_home"})
    assert state["home_active"] and state["control_active"]
    assert sim.finger_target == pytest.approx(0.04)
    assert not sim.grip.rates
    now[0] += 0.1
    state = sim.apply({"method": "get_state"})
    assert sim.trajectory is None  # The arm was already home; the gripper was not.
    assert state["home_active"] and state["control_active"]
    with pytest.raises(ValueError, match="busy"):
        sim.apply({"method": "jog_gripper", "params": {"velocity": {"hand": -0.2}}})
    with pytest.raises(ValueError, match="moving home"):
        sim.apply({"method": "set_home"})
    if finish == "complete":
        sim.feedback["grippers"]["hand"] = 1.0
    elif finish == "stop":
        sim.apply({"method": "hold"})
    else:
        now[0] = sim.deadline + 1
    state = sim.apply({"method": "get_state"})
    assert not state["home_active"] and not state["control_active"]
    assert sim.finger_target == pytest.approx(0.04 if finish == "complete" else 0.014)
