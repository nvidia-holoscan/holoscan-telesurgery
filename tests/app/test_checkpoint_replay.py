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
            assert abs(values[3]) <= 1
            assert abs(values[4]) <= 5
            assert command["left"] == [0] * 5
            playback.validate_request(mode, command)
            # An accepted increment only partly becomes measured motion.
            actual = [a + 0.6 * v for a, v in zip(actual, values, strict=True)]
            playback.acknowledge(state(actual))
            issued += 1
        now[0] += delay
    else:
        pytest.fail("Recorded pose was not reached")
    assert issued > 1


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


def test_loaded_lift_tolerance_does_not_relax_precise_grasp_arrival():
    goal = [0, 25, 0, 0, 0]
    measured = state([0, 24.8, 0, 0, 0])
    measured["control_active"] = False
    precise = player([row(pose={"right": goal})], [0.0])
    assert not precise.read(0, measured)["done"]
    lift = player([row(pose={"right": goal}, position_tolerance_mm=0.25)], [0.0])
    assert lift.read(0, measured)["done"]


@pytest.mark.parametrize("tolerance", [0, 0.3, True, float("nan"), "0.25"])
def test_pose_tolerance_cannot_remove_measured_arrival_bounds(tolerance):
    with pytest.raises(ValueError, match="pose tolerance"):
        validate_checkpoints([row(pose={"right": [0] * 5}, position_tolerance_mm=tolerance)])


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


def test_closing_contact_allows_compliant_jaws_to_spread_slightly():
    now = [0.0]
    playback = player([row(grip={"right": 0})], now)
    for tick in range(20):
        now[0] = tick * 0.1
        result = playback.read(now[0], {"grippers": {"right": 0.04 + tick * 0.001}})
        if result["done"]:
            assert now[0] >= 1.2
            break
        playback.acknowledge({})
    else:
        pytest.fail("Compliant contact never completed")


def test_stuck_open_gripper_is_not_accepted_as_needle_contact():
    now = [0.0]
    playback = player([row(grip={"right": 0})], now)
    for tick in range(50):
        now[0] = tick * 0.1
        assert not playback.read(now[0], {"grippers": {"right": 0.5}})["done"]
        playback.acknowledge({})
    now[0] = 5.1
    with pytest.raises(TimeoutError, match="checkpoint"):
        playback.read(now[0], {"grippers": {"right": 0.5}})


def test_delayed_gripper_feedback_slows_approach_to_opening_target():
    now = [0.0]
    playback = player([row(grip={"right": 0.25})], now)
    measured = {"grippers": {"right": 0.24}}
    initial = playback.read(0, measured)["request"][1]["right"]
    playback.acknowledge({})
    now[0] = 0.35
    playback.read_at = now[0]
    delayed = playback.read(now[0], measured)["request"][1]["right"]
    assert 0 < delayed < initial
    assert delayed * 0.7 == pytest.approx(0.01)


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


def cartesian_robot(environment):
    from telesurgery_robots.adapters.simulation import FrankaSimulation, VersiusSimulation

    adapter = (FrankaSimulation if environment == "franka" else VersiusSimulation)(
        {"uri": "unused"}
    )
    return {"kind": environment + "-sim", "controls": controls(adapter, {})}


def tool_state(position, *, rotation=None, velocity=0):
    return {
        "tool_pose": {
            "frame": "base",
            "end_effector": "TCP",
            "position_m": position,
            "orientation_matrix": rotation or [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        },
        "velocity_deg_s": {"joints": [velocity] * 7},
        "control_active": velocity != 0,
    }


def test_delayed_tool_feedback_reduces_correction_without_changing_arrival_tolerance():
    now = [0.0]
    target = tool_state([0, 0, 0])["tool_pose"]
    playback = CheckpointPlayback(
        cartesian_robot("franka"),
        {"device": "keyboard"},
        "franka",
        [row(tool_pose=target)],
        "run",
        lambda: now[0],
    )
    measured = tool_state([0.002, 0, 0])
    local = playback.read(0, measured)["request"][1]["translation"][0]
    playback.acknowledge({})
    now[0] = 0.35
    playback.read_at = now[0]  # Dashboard heartbeat is independent of feedback.
    delayed = playback.read(now[0], measured)["request"][1]["translation"][0]
    assert delayed == pytest.approx(local / 2)
    assert not playback.finished
    playback.acknowledge({})
    now[0] += 0.1
    result = playback.read(now[0], tool_state([0.0002, 0, 0]))
    assert result["done"]


@pytest.mark.parametrize("environment", ["franka", "versius"])
@pytest.mark.parametrize("device", ["keyboard", "gamepad", "haply"])
@pytest.mark.parametrize("delay", [0.05, 0.12, 0.24])
def test_cartesian_checkpoints_follow_measured_pose_under_delayed_delivery(
    environment, device, delay
):
    import numpy as np

    now = [0.0]
    goal = tool_state([0.04, -0.02, 0.01])["tool_pose"]
    playback = CheckpointPlayback(
        cartesian_robot(environment),
        {"device": device},
        "arm",
        [row(tool_pose=goal)],
        "run",
        lambda: now[0],
    )
    actual = np.zeros(3)
    for _ in range(400):
        result = playback.read(now[0], tool_state(actual.tolist()))
        if result["done"]:
            assert np.linalg.norm(actual - goal["position_m"]) <= 0.00025
            break
        mode, command = result["request"]
        assert mode == "jog"
        assert np.linalg.norm(command["translation"]) <= 1 + 1e-9
        assert np.linalg.norm(command["rotation"]) <= 1 + 1e-9
        playback.validate_request(mode, command)
        # Delivery/servo speed changes do not change the recorded destination.
        actual += np.array(command["translation"]) * 0.1 * delay * 0.7
        playback.acknowledge(tool_state(actual.tolist()))
        now[0] += delay
    else:
        pytest.fail("Tool checkpoint was not reached")


def test_cartesian_arrival_waits_for_braking_and_corrects_stop_drift():
    now = [0.0]
    goal = tool_state([0.01, 0, 0])["tool_pose"]
    playback = CheckpointPlayback(
        cartesian_robot("franka"),
        {"device": "keyboard"},
        "franka",
        [row(tool_pose=goal), row(hold_s=1)],
        "run",
        lambda: now[0],
    )
    moving = tool_state([0.01, 0, 0], velocity=1)
    assert playback.read(0, moving)["request"] == ("release", {})
    assert playback.index == 0
    now[0] = 0.1
    result = playback.read(0.1, tool_state([0.011, 0, 0]))
    assert result["request"][1]["translation"][0] < 0
    assert playback.index == 0


def test_stalled_tool_checkpoint_times_out_and_invalid_feedback_is_rejected():
    now = [0.0]
    playback = CheckpointPlayback(
        cartesian_robot("franka"),
        {"device": "haply"},
        "franka",
        [row(tool_pose=tool_state([0.1, 0, 0])["tool_pose"])],
        "run",
        lambda: now[0],
    )
    with pytest.raises(ValueError, match="tool pose feedback"):
        playback.read(0, {})
    for _ in range(21):
        playback.read(now[0], tool_state([0, 0, 0]))
        playback.acknowledge({})
        now[0] += 0.25
    with pytest.raises(TimeoutError, match="checkpoint"):
        playback.read(now[0], tool_state([0, 0, 0]))


def test_handoff_waits_for_peer_checkpoint_without_using_recorded_time():
    now = [0.0]
    playback = CheckpointPlayback(
        cartesian_robot("versius"),
        {"device": "gamepad"},
        "left",
        [row(barrier=1), row(grip={"hand": 1})],
        "run",
        lambda: now[0],
    )
    for _ in range(50):
        result = playback.read(1000, {})
        assert result.get("waiting_peer") and not result["request"]
        assert playback.checkpoint == 1 and playback.index == 0
        now[0] += 0.2
    playback.synchronized = 1
    playback.read(1000, {})
    assert playback.index == 1


@pytest.mark.parametrize("environment", ["mira", "franka", "versius"])
def test_catalog_has_checkpoints_for_every_device(environment):
    from telesurgery.controller.replay import Catalog, read_rows

    catalog = Catalog()
    for device in ("keyboard", "gamepad", "haply"):
        path, manifest = catalog.recordings[f"{environment}/{device}"]
        assert manifest["version"] == 2
        for spec in manifest["streams"].values():
            validate_checkpoints(
                read_rows(path.parent / spec["file"]), environment=environment, device=device
            )


def test_mira_rebases_after_delayed_delivery_outlives_jog_watchdog():
    now = [0.0]
    playback = player([row(pose={"right": [1, 0, 0, 0, 0]})], now)
    feedback = state([0, 0, 0, 0, 0])
    feedback.update(control_active=False)
    feedback["cartesian_target_mm_deg"]["right"][0] = 1
    result = playback.read(0, feedback)
    # The next ordinary jog starts from measured joints after the watchdog has
    # held the robot. The old drive target is not pending travel anymore.
    assert result["request"][1]["right"][0] == 1


def test_mira_reobserves_pending_travel_before_final_correction_and_grasp():
    now = [0.0]
    playback = player([row(pose={"right": [1, 0, 0, 0, 0]}), row(grip={"right": 0})], now)
    feedback = state([0.88, 0, 0, 0, 0])
    feedback["control_active"] = True
    feedback["cartesian_target_mm_deg"]["right"][0] = 1
    # At a high RTT the pending target may expire before the next jog arrives.
    # Hold and re-observe rather than subtracting travel that will be discarded.
    assert playback.read(0, feedback)["request"] == ("release", {})
    assert playback.index == 0
    now[0] = 0.2
    feedback["control_active"] = False
    correction = playback.read(0.2, feedback)["request"]
    assert correction[0] == "cartesian"
    assert correction[1]["right"][0] == pytest.approx(0.12)
    playback.acknowledge(feedback)
    now[0] = 0.4
    feedback = state([1, 0, 0, 0, 0])
    feedback["control_active"] = True
    assert playback.read(0.4, feedback)["request"] == ("release", {})
    assert playback.index == 1


@pytest.mark.parametrize("angle", [0.7, 3.141592653589793])
def test_tool_orientation_converges_with_delayed_feedback_including_half_turn(angle):
    import numpy as np

    def rotation(theta):
        return np.array(
            [[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]]
        )

    now = [0.0]
    goal = tool_state([0, 0, 0], rotation=rotation(angle).tolist())["tool_pose"]
    playback = CheckpointPlayback(
        cartesian_robot("versius"),
        {"device": "haply"},
        "left",
        [row(tool_pose=goal)],
        "run",
        lambda: now[0],
    )
    actual = 0.0
    for _ in range(400):
        result = playback.read(now[0], tool_state([0, 0, 0], rotation=rotation(actual).tolist()))
        if result["done"]:
            assert np.linalg.norm(rotation(actual) - rotation(angle)) < 0.008
            break
        mode, command = result["request"]
        assert mode == "jog"
        assert command["translation"] == [0, 0, 0]
        assert np.linalg.norm(command["rotation"]) <= 1 + 1e-9
        actual += command["rotation"][2] * np.deg2rad(30) * 0.2 * 0.7
        playback.acknowledge({})
        now[0] += 0.2
    else:
        pytest.fail("Orientation checkpoint was not reached")


def test_versius_joint_preparation_waits_for_measured_arrival_and_settles():
    now = [0.0]
    goal = [0, -40, 10, 100, -20, 20, -20, 110]
    playback = CheckpointPlayback(
        cartesian_robot("versius"),
        {"device": "gamepad"},
        "left",
        [row(joint_pose=goal)],
        "run",
        lambda: now[0],
    )
    feedback = {
        "joints_deg": {"joints": [v + 1 for v in goal]},
        "targets_deg": {"joints": [v + 1 for v in goal]},
        "control_active": True,
    }
    result = playback.read(0, feedback)
    assert result["request"] == ("step", {"joints": [-1] * 8})
    playback.acknowledge({})
    now[0] = 0.1
    assert playback.read(0.1, feedback)["waiting_feedback"]
    now[0] = 0.2
    feedback["control_active"] = False
    feedback["targets_deg"]["joints"] = goal
    assert playback.read(0.2, feedback)["request"] is None
    assert not playback.finished
    now[0] = 0.3
    feedback["joints_deg"]["joints"] = goal
    assert playback.read(0.3, feedback)["done"]


@pytest.mark.parametrize("maximum", [1, 5])
def test_joint_preparation_uses_advertised_step_bound_and_waits_for_completion(maximum):
    now = [0.0]
    robot = cartesian_robot("versius")
    robot["controls"]["max_step_deg"] = maximum
    goal = [0, -40, 10, 100, -20, 20, -20, 110]
    playback = CheckpointPlayback(
        robot, {"device": "keyboard"}, "left", [row(joint_pose=goal)], "run", lambda: now[0]
    )
    feedback = {
        "joints_deg": {"joints": [v - 10 for v in goal]},
        "targets_deg": {"joints": [v - 10 for v in goal]},
        "control_active": False,
    }
    assert playback.read(0, feedback)["request"] == ("step", {"joints": [maximum] * 8})
    playback.acknowledge({})
    feedback["control_active"] = True
    for tick in range(1, 6):
        now[0] = tick * 0.2
        result = playback.read(now[0], feedback)
        assert result["request"] is None
        assert result["waiting_feedback"]


@pytest.mark.parametrize("target", [[0] * 7, [0] * 9, [0, -40, 10, 100, -20, 30, -20, 110]])
def test_joint_preparation_rejects_incomplete_or_out_of_bounds_targets(target):
    with pytest.raises(ValueError):
        validate_checkpoints([row(joint_pose=target)], environment="versius", device="haply")
