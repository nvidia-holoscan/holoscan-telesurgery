# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Haply input must rearm explicitly and retain the bounded MIRA control contract."""

import copy
import math
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from telesurgery.controller.haply import (
    BrowserHaply,
    Haply,
    MiraHaply,
    Sample,
    Tracking,
    available,
    decode,
    pen_tilt,
)
from telesurgery.controller.input import Inputs
from telesurgery.server.application import Application
from telesurgery_robots.mira.cartesian import CARTESIAN, SIM_CARTESIAN, command


@pytest.mark.parametrize(
    "product", ["Haply inverse3", "Haply USB Transceiver", "Other serial device"]
)
@pytest.mark.parametrize("visible", [False, True])
def test_haply_discovery_needs_a_visible_usb_endpoint_not_calibration(tmp_path, product, visible):
    sysfs, dev, usb = (tmp_path / name for name in ("sys", "dev", "usb"))
    for directory in (sysfs, dev, usb):
        directory.mkdir()
    (usb / "product").write_text(product)
    endpoint = usb / "interface" / "ttyACM0"
    endpoint.mkdir(parents=True)
    (sysfs / "ttyACM0").symlink_to(endpoint)
    if visible:
        (dev / "ttyACM0").touch()
    assert available(sysfs, dev) == (visible and product.startswith("Haply"))
    (usb / "product").unlink()
    assert not available(sysfs, dev)


@pytest.fixture
def robot():
    return {
        "id": "test:mira",
        "kind": "mira-sim",
        "status": "online",
        "controls": {
            "groups": {"left": 5, "right": 5},
            "mira_cartesian": CARTESIAN,
            "grippers": ["left", "right"],
            "reset_scene": True,
            "grip_speed_pct_s": {"max": 50},
        },
        "state": {
            "grippers": {"left": 0.0, "right": 1.0},
            "cartesian_mm_deg": {
                "left": [100.0, 200.0, 300.0, 45.0],
                "right": [-100.0, 200.0, 300.0, 45.0],
            },
            "joints_deg": {"left": [0.0] * 5, "right": [0.0] * 5},
        },
    }


class Driver:
    def __init__(self, robot):
        self.mapper = MiraHaply()
        self.inputs = Inputs(robot)
        self.state = robot["state"]
        self.now = 1.0
        self.sample = Sample(("base", "grip"), (0, 0, 0), (0, 0, 0, 1), frozenset(), self.now)

    def tick(self, *, ready=True, **changes):
        self.now += 0.05
        if "angles" in changes:
            x, y = (math.radians(v) / 2 for v in changes.pop("angles"))
            changes["orientation"] = (
                math.sin(x) * math.cos(y),
                math.cos(x) * math.sin(y),
                math.sin(x) * math.sin(y),
                math.cos(x) * math.cos(y),
            )
        self.sample = replace(self.sample, received=self.now, **changes)
        return self.mapper.update(self.sample, self.state, self.inputs, self.now, ready=ready)

    def resume(self):
        self.tick(buttons=frozenset())
        self.tick(buttons=frozenset("a"))
        self.tick(buttons=frozenset())
        assert not self.mapper.paused


def test_missing_optional_transport_reports_setup_without_breaking_native_import(monkeypatch):
    import builtins

    original = builtins.__import__

    def without_websocket(name, *args, **kwargs):
        if name == "websocket":
            raise ImportError("No websocket")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_websocket)
    reader = Haply()
    try:
        reader.thread.join(timeout=1)
        sample, error = reader.sample(time.monotonic())
        assert sample is None and "setup.sh" in error
    finally:
        reader.close()


def test_motion_waits_for_start_button_and_follows_latest_target(robot):
    driver = Driver(robot)
    assert driver.tick(position=(0.2, 0, 0)) is None
    assert driver.mapper.paused  # Pen travel before Start never becomes a robot move.
    driver.resume()
    mode, values = driver.tick(position=(0.201, 0.002, 0.003), angles=(0, 2))
    assert mode == "cartesian"
    command(values)
    assert values["right"] == [0] * 5
    assert values["left"][0] > 0 and values["left"][1] < 0 and values["left"][2] > 0
    assert math.hypot(*values["left"][:3]) == pytest.approx(0.1)
    assert values["left"][4] == 0.5
    # A stationary but live pen retains its desired position while the robot catches up.
    assert driver.tick()[0] == "cartesian"
    driver.state["cartesian_mm_deg"]["left"][:3] = [101.4, 199.3, 302.1]
    driver.state["joints_deg"]["left"][4] = 2
    assert driver.tick() == ("release", {})
    assert driver.tick() is None


def test_button_tap_switches_on_release_and_rebases_each_arm(robot):
    driver = Driver(robot)
    driver.resume()
    assert driver.tick(buttons=frozenset("b")) == ("release", {})
    assert driver.mapper.arm == "left"
    for i in range(4):
        assert driver.tick(position=(0.005 * i, 0, 0)) is None
    assert driver.tick(buttons=frozenset()) == ("release", {})
    assert driver.mapper.arm == "right"
    assert driver.tick() is None  # Travel while switching is never replayed.
    mode, command = driver.tick(position=(0.015, 0.001, 0))
    assert mode == "cartesian" and command["left"] == [0] * 5
    assert command["right"][0] == pytest.approx(0.1)
    driver.tick(buttons=frozenset("b"))
    driver.tick(buttons=frozenset())
    assert driver.mapper.arm == "left"


def test_haply_does_not_duplicate_unfinished_robot_travel(robot):
    driver = Driver(robot)
    driver.resume()
    # The robot has accepted this target but physics is still catching up.
    driver.state["cartesian_target_mm_deg"] = {"left": [100.7, 200, 300, 45]}
    mode, values = driver.tick(position=(0, 0.001, 0))
    assert mode == "cartesian"
    assert values == {"left": [0] * 5, "right": [0] * 5}
    # Zero refreshes retain the target until measured arrival; then hold.
    driver.state["cartesian_mm_deg"]["left"][0] = 100.7
    assert driver.tick() == ("release", {})
    # A new pen position replaces the target; there is no queued old travel.
    assert driver.tick(position=(0, 0, 0))[1]["left"][0] == pytest.approx(-0.1)


def hold_grip(driver, button="b"):
    driver.tick(buttons=frozenset(button))
    for _ in range(13):
        result = driver.tick()
    return result


@pytest.mark.parametrize("button, direction", [("a", -1), ("b", 1)])
def test_hold_grips_only_while_held_without_switch_or_pause(robot, button, direction):
    driver = Driver(robot)
    driver.resume()
    assert hold_grip(driver, button) == ("grip", {"left": direction * 0.2})
    for _ in range(30):
        assert driver.tick() == ("grip", {"left": direction * 0.2})
        assert driver.mapper.arm == "left" and not driver.mapper.paused
    assert driver.tick(buttons=frozenset()) == ("release", {})
    assert driver.tick() is None
    assert driver.mapper.arm == "left" and not driver.mapper.paused
    assert driver.tick(position=(0, 0.001, 0))[0] == "cartesian"


def test_grip_is_disabled_when_stopped_or_feedback_missing(robot):
    driver = Driver(robot)
    driver.tick()
    assert hold_grip(driver) is None
    driver.tick(buttons=frozenset())
    assert driver.mapper.arm == "left" and driver.mapper.paused
    driver.resume()
    del driver.state["grippers"]["left"]
    hold_grip(driver)
    assert driver.mapper.paused and "gripper feedback" in driver.mapper.error


def test_stop_requires_fresh_button_and_resumes_without_switching(robot):
    driver = Driver(robot)
    driver.resume()
    driver.tick(buttons=frozenset("b"))
    driver.tick(buttons=frozenset())
    assert driver.mapper.arm == "right"
    driver.mapper.halt()
    for _ in range(5):
        driver.tick()
        assert driver.mapper.paused  # Holding the button through Stop cannot resume.
    driver.tick(buttons=frozenset())
    driver.tick(buttons=frozenset("a"))
    driver.tick(buttons=frozenset())
    assert not driver.mapper.paused and driver.mapper.arm == "right"
    assert driver.tick() is None


def test_pen_stop_toggle_and_arm_switch_while_stopped(robot):
    driver = Driver(robot)
    driver.tick()
    driver.tick(buttons=frozenset("b"))
    driver.tick(buttons=frozenset())
    assert driver.mapper.paused and driver.mapper.arm == "right"
    driver.resume()
    assert driver.tick(buttons=frozenset("a")) == ("release", {})
    assert driver.tick(buttons=frozenset()) == ("release", {})
    assert driver.mapper.paused and driver.mapper.arm == "right"
    driver.tick(buttons=frozenset("a"))
    driver.tick(buttons=frozenset())
    assert not driver.mapper.paused
    assert driver.tick(buttons=frozenset("c")) == ("release", {})
    assert driver.mapper.paused


def test_backpressure_uses_current_pen_target_without_queued_travel(robot):
    driver = Driver(robot)
    driver.resume()
    assert driver.tick(ready=False, position=(0.01, 0, 0)) is None
    assert driver.tick(position=(0, 0, 0)) is None  # Pen returned while request was busy.
    driver.tick(ready=False, position=(0.01, 0, 0))
    assert driver.tick()[1]["left"][1] == pytest.approx(-0.1)
    driver.mapper.halt()
    driver.tick(position=(0.02, 0, 0))
    driver.tick(buttons=frozenset("a"))
    driver.tick(buttons=frozenset())
    assert driver.tick() is None


@pytest.mark.parametrize(
    "change",
    [
        {"position": (1, 0, 0)},
        {"angles": (0, 90)},
        {"generation": 2},
        {"identity": ("different-base", "grip")},
    ],
)
def test_discontinuity_or_reconnect_requires_fresh_resume(robot, change):
    driver = Driver(robot)
    driver.resume()
    assert driver.tick(**change) == ("release", {})
    assert driver.mapper.paused
    assert driver.tick() is None
    assert driver.mapper.error


@pytest.mark.parametrize("motion", ["translation", "twist"])
def test_continuous_fast_pen_motion_survives_slower_control_polls(robot, motion):
    driver = Driver(robot)
    driver.resume()
    tracking = Tracking()
    first = tracking.observe(driver.sample)
    driver.mapper.update(first, driver.state, driver.inputs, first.received)
    # Ten device samples arrive while one 100 ms control round trip completes.
    # The aggregate movement exceeds the old 5 cm / 45 degree poll thresholds.
    for i in range(1, 11):
        angle = math.radians(7 * i if motion == "twist" else 0) / 2
        latest = tracking.observe(
            replace(
                driver.sample,
                received=first.received + 0.01 * i,
                position=(0.008 * i if motion == "translation" else 0, 0, 0),
                orientation=(0, math.sin(angle), 0, math.cos(angle)),
            )
        )
    result = driver.mapper.update(latest, driver.state, driver.inputs, latest.received)
    assert result[0] == "cartesian"
    assert not driver.mapper.paused
    if motion == "twist":
        assert driver.mapper.rotation == pytest.approx(70)


@pytest.mark.parametrize("fault", ["position", "orientation", "disconnect"])
def test_tracking_fault_between_control_polls_still_requires_restart(robot, fault):
    driver = Driver(robot)
    driver.resume()
    tracking = Tracking()
    first = tracking.observe(driver.sample)
    driver.mapper.update(first, driver.state, driver.inputs, first.received)
    bad = replace(driver.sample, received=first.received + 0.01)
    if fault == "position":
        bad = replace(bad, position=(0.1, 0, 0))
    elif fault == "orientation":
        bad = replace(bad, orientation=(0, 1, 0, 0))
    else:
        bad = None
    tracking.observe(bad)
    # The pen returns before the next poll. A discarded intermediate fault
    # must not be hidden by an apparently unchanged latest sample.
    latest = tracking.observe(replace(driver.sample, received=first.received + 0.02))
    assert driver.mapper.update(latest, driver.state, driver.inputs, latest.received) == (
        "release",
        {},
    )
    assert driver.mapper.paused and "tracking jumped" in driver.mapper.error
    latest = tracking.observe(replace(driver.sample, received=first.received + 0.03))
    assert driver.mapper.update(latest, driver.state, driver.inputs, latest.received) is None
    assert "tracking jumped" in driver.mapper.error


def test_stale_tracking_stops_pending_target_and_handles_wrapped_angles(robot):
    driver = Driver(robot)
    driver.tick(angles=(0, 179))
    driver.resume()
    assert driver.tick(angles=(0, -179))[1]["left"][4] == 0.5
    assert driver.mapper.update(driver.sample, driver.state, driver.inputs, driver.now + 0.3) == (
        "release",
        {},
    )
    assert driver.mapper.paused
    assert driver.tick() is None


def test_missing_cartesian_feedback_never_moves(robot):
    driver = Driver(robot)
    del driver.state["cartesian_mm_deg"]
    driver.resume()
    assert driver.tick(position=(0.001, 0, 0)) is None
    assert "feedback" in driver.mapper.error


@pytest.fixture
def frame():
    return {
        "inverse3": [
            {
                "device_id": "base",
                "status": {
                    "power_supply": True,
                    "calibrated": True,
                    "ready": True,
                    "started": True,
                },
                "state": {"cursor_position": {"x": 0, "y": 0, "z": 0}},
            }
        ],
        "wireless_verse_grip": [
            {
                "device_id": "grip",
                "status": {
                    "connected": True,
                    "awake": True,
                    "ready": True,
                },
                "state": {
                    "buttons": {"a": False, "b": False, "c": False},
                    "orientation": {"x": 0, "y": 0, "z": 0, "w": 1},
                },
            }
        ],
    }


def test_decode_validates_readiness_and_finite_tracking(frame):
    assert decode(frame, 1).orientation == (0, 0, 0, 1)
    frame["inverse3"][0]["status"]["power_supply"] = False
    assert decode(frame, 1).position == (0, 0, 0)  # USB-only tracking is supported.
    for family, key in [
        ("inverse3", "calibrated"),
        ("inverse3", "ready"),
        ("wireless_verse_grip", "awake"),
        ("wireless_verse_grip", "connected"),
    ]:
        invalid = copy.deepcopy(frame)
        invalid[family][0]["status"][key] = False
        with pytest.raises(ValueError):
            decode(invalid, 1)
    for invalid in [float("nan"), float("inf"), None]:
        frame["inverse3"][0]["state"]["cursor_position"]["x"] = invalid
        with pytest.raises(ValueError):
            decode(frame, 1)


@pytest.mark.parametrize("roll_step", [1, 5])
def test_orientation_decoding_drives_selected_tool_roll_only(robot, frame, roll_step, monkeypatch):
    monkeypatch.setitem(robot["controls"]["mira_cartesian"], "roll_step_deg", roll_step)
    driver = Driver(robot)
    driver.tick()
    driver.tick(buttons=frozenset("b"))
    driver.tick(buttons=frozenset())
    driver.resume()
    angle = math.radians(10) / 2
    frame["wireless_verse_grip"][0]["state"]["orientation"] = {
        "x": 0,
        "y": math.sin(angle),
        "z": 0,
        "w": math.cos(angle),
    }
    orientation = decode(frame, driver.now).orientation
    mode, command = driver.tick(orientation=orientation)
    assert mode == "cartesian"
    assert command["left"] == [0] * 5
    assert command["right"] == [0, 0, 0, 0, 0.5 * roll_step]


@pytest.mark.parametrize("arm, sign", [("left", -1), ("right", -1)])
@pytest.mark.parametrize("degrees", [-12, 12])
def test_pen_tilt_angles_selected_tool_without_translation_or_roll(robot, arm, sign, degrees):
    driver = Driver(robot)
    driver.mapper.arm = arm
    driver.resume()
    mode, values = driver.tick(angles=(degrees, 0))
    assert mode == "cartesian"
    command(values)
    assert values[arm] == pytest.approx([0, 0, 0, sign * math.copysign(0.2, degrees), 0])
    assert values["right" if arm == "left" else "left"] == [0] * 5
    # Accepted elbow travel is refreshed, never added again while physics catches up.
    target = [100, 200, 300, 45 + sign * degrees]
    target[:3] = driver.state["cartesian_mm_deg"][arm][:3]
    driver.state["cartesian_target_mm_deg"] = {arm: target}
    assert driver.tick() == ("cartesian", {"left": [0] * 5, "right": [0] * 5})
    driver.state["cartesian_mm_deg"][arm] = list(target)
    assert driver.tick() == ("release", {})
    assert driver.tick() is None
    # Returning the pen commands the opposite direction without a queued old target.
    assert driver.tick(angles=(0, 0))[1][arm][3] == pytest.approx(
        -sign * math.copysign(0.2, degrees)
    )


@pytest.mark.parametrize("roll", [0, 90, 180, 270])
@pytest.mark.parametrize("yaw", [0, 90, 180])
def test_pen_elevation_is_independent_of_roll_and_horizontal_heading(roll, yaw):
    # Rz(yaw) Rx(30 degrees) Ry(roll): change heading and axial roll while
    # maintaining the pen's physical elevation at 30 degrees.
    x, y, z = (math.radians(v) / 2 for v in (30, roll, yaw))
    quat = (
        math.cos(z) * math.sin(x) * math.cos(y) - math.sin(z) * math.cos(x) * math.sin(y),
        math.cos(z) * math.cos(x) * math.sin(y) + math.sin(z) * math.sin(x) * math.cos(y),
        math.cos(z) * math.sin(x) * math.sin(y) + math.sin(z) * math.cos(x) * math.cos(y),
        math.cos(z) * math.cos(x) * math.cos(y) - math.sin(z) * math.sin(x) * math.sin(y),
    )
    assert pen_tilt(quat) == pytest.approx(30)
    assert pen_tilt(tuple(-v for v in quat)) == pytest.approx(30)


def test_tilt_and_translation_work_together_and_rebase_after_stop_and_arm_switch(robot):
    driver = Driver(robot)
    driver.tick(angles=(20, 0))
    driver.resume()
    assert driver.tick() is None  # Starting with an angled pen never moves the tool.
    mode, values = driver.tick(angles=(30, 0), position=(0, 0.001, 0))
    assert mode == "cartesian"
    assert values["left"] == pytest.approx([0.1, 0, 0, -0.2, 0])
    driver.mapper.halt()
    driver.tick(angles=(-10, 0))
    driver.resume()
    assert driver.tick() is None
    driver.tick(buttons=frozenset("b"))
    driver.tick(angles=(-20, 0))
    driver.tick(buttons=frozenset())
    assert driver.mapper.arm == "right" and not driver.mapper.paused
    assert driver.tick() is None
    assert driver.tick(angles=(-15, 0))[1]["right"][3] == pytest.approx(-0.2)


def test_pen_roll_crosses_euler_singularity_and_quaternion_sign_without_pause(robot):
    driver = Driver(robot)
    driver.tick(angles=(0, 85))
    driver.resume()
    for angle in range(90, 191, 5):
        request = driver.tick(angles=(0, angle))
        assert not driver.mapper.paused
        assert request[0] == "cartesian" and request[1]["left"][4] > 0
    before = driver.mapper.rotation
    driver.tick(orientation=tuple(-v for v in driver.sample.orientation))
    assert not driver.mapper.paused and driver.mapper.rotation == pytest.approx(before)


def test_simulation_speed_does_not_increase_physical_mira_limits(robot):
    robot["controls"]["mira_cartesian"] = SIM_CARTESIAN
    driver = Driver(robot)
    driver.resume()
    _, values = driver.tick(position=(0, 0.04, 0))
    assert math.hypot(*values["left"][:3]) == pytest.approx(1.0)
    command(values, SIM_CARTESIAN)
    with pytest.raises(ValueError, match="0.5 mm"):
        command(values, CARTESIAN)
    driver.inputs.arm_percent = 100
    _, values = driver.tick()
    assert math.hypot(*values["left"][:3]) == pytest.approx(5.0)


@pytest.mark.parametrize("arm", ["left", "right"])
@pytest.mark.parametrize("axis, world_axis", [(0, 2), (1, 0), (2, 1)])
@pytest.mark.parametrize("sign", [-1, 1])
def test_simulated_pen_axes_follow_right_forward_and_up(robot, arm, axis, world_axis, sign):
    robot["controls"]["mira_cartesian"] = SIM_CARTESIAN
    driver = Driver(robot)
    driver.mapper.arm = arm
    driver.resume()
    position = [0.0] * 3
    position[axis] = sign * 0.001
    mode, values = driver.tick(position=tuple(position))
    assert mode == "cartesian"
    x, y, z = values[arm][:3]
    # MIRA's simulation base maps into its Y-up stage as (Z, Y, -X).
    world = [z, y, -x]
    expected = [0.0] * 3
    expected[world_axis] = sign * 0.7
    assert world == pytest.approx(expected)


def test_reader_uses_monitoring_probes_and_closes_only_its_connection(monkeypatch, frame):
    import json

    connection = Mock()
    connection.recv.return_value = json.dumps(frame)
    monkeypatch.setattr(
        "websocket.create_connection",
        lambda *args, **kwargs: connection,
    )
    reader = Haply()
    try:
        deadline = time.monotonic() + 2
        while reader.latest[0] is None and time.monotonic() < deadline:
            time.sleep(0.01)
        sample, error = reader.sample(time.monotonic())
        assert sample and not error
        request = json.loads(connection.send.call_args.args[0])
        assert request["inverse3"][0]["commands"] == {"probe_position": {}}
        assert request["wireless_verse_grip"][0]["commands"] == {"probe_orientation": {}}
        assert reader.process is None
        assert reader.sample(sample.received + 1)[0] is None
    finally:
        reader.close()
    assert not reader.thread.is_alive()
    connection.close.assert_called_once()


@pytest.mark.parametrize("exit_code", [None, 1])
@pytest.mark.parametrize("executable_available", [False, True])
def test_reader_restarts_only_an_exited_managed_service(
    monkeypatch, exit_code, executable_available
):
    # Run three refused connections synchronously, without hardware or real processes.
    monkeypatch.setattr("telesurgery.controller.haply.threading.Thread", Mock())
    monkeypatch.setattr("websocket.create_connection", Mock(side_effect=ConnectionRefusedError))
    executable = "/usr/bin/haply-inverse-service"
    monkeypatch.setattr(
        "telesurgery.controller.haply.shutil.which",
        Mock(side_effect=[executable] + [executable if executable_available else None] * 2),
    )
    first, second = Mock(), Mock()
    first.poll.return_value = exit_code
    second.poll.return_value = None
    spawn = Mock(side_effect=[first, second])
    monkeypatch.setattr("telesurgery.controller.haply.subprocess.Popen", spawn)
    logs = [Mock(), Mock()]
    create_log = Mock(side_effect=logs)
    monkeypatch.setattr("telesurgery.controller.haply.tempfile.TemporaryFile", create_log)
    reader = Haply()
    reader.done = Mock()
    reader.done.is_set.side_effect = [False, False, False, True]
    reader._run()
    restarted = exit_code is not None and executable_available
    assert spawn.call_count == create_log.call_count == (2 if restarted else 1)
    logs[0].close.assert_called_once()
    if exit_code is None:
        first.terminate.assert_called_once()
        first.wait.assert_called_once_with(timeout=3)
    else:
        first.terminate.assert_not_called()
    if restarted:
        logs[1].close.assert_called_once()
        second.terminate.assert_called_once()
        second.wait.assert_called_once_with(timeout=3)
    else:
        second.terminate.assert_not_called()
    assert reader.latest[0] is None


def test_browser_token_change_disabled_input_and_poll_gap_rearm(monkeypatch, robot):
    now = [1.0]
    sample = [Sample(("base", "grip"), (0, 0, 0), (0, 0, 0, 1), frozenset(), now[0])]
    monkeypatch.setattr("telesurgery.controller.haply.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "telesurgery.controller.haply.Haply",
        lambda: SimpleNamespace(sample=lambda _: (sample[0], ""), close=lambda: None),
    )
    browser = BrowserHaply()
    params = {"token": "tab-1:0", "enabled": True}

    def read(buttons="", seconds=0.05):
        now[0] += seconds
        sample[0] = replace(sample[0], received=now[0], buttons=frozenset(buttons))
        return browser.read(robot, params)

    assert read()["paused"]  # Selecting Haply never starts movement.
    read("a")
    assert not read()["paused"]
    read()
    params["token"] = "tab-1:1"
    assert read("a")["paused"]
    read()
    read("a")
    assert not read()["paused"]
    assert read(seconds=0.5)["paused"]
    read("a")
    assert not read()["paused"]
    params["enabled"] = False
    assert read()["paused"]
    params["speeds"] = {"arm": float("nan")}
    with pytest.raises(ValueError, match="percent"):
        read()
    params["speeds"] = {}
    robot["kind"] = "mira"
    assert read()["paused"]  # Physical MIRA shares the published tool contract.
    robot["controls"] = {}
    with pytest.raises(ValueError, match="Cartesian control"):
        read()


@pytest.mark.asyncio
async def test_browser_api_checks_permission_and_robot_ownership(robot):
    app = Application.__new__(Application)
    app.role = "surgeon"
    app.remote_status = {"status": "pending", "robot": True, "id": "me", "robots": [robot]}
    app.haply = Mock()
    app.robot_state = {}
    with pytest.raises(PermissionError):
        await app.action("haply.read", {"id": robot["id"]})
    app.haply.read.assert_not_called()
    app.remote_status["status"] = "approved"
    # Latest command acknowledgement can precede the slower inventory poll.
    robot["state"]["sequence"] = 1
    app.robot_state[robot["id"]] = {**robot["state"], "sequence": 2}
    await app.action("haply.read", {"id": robot["id"], "enabled": True})
    assert app.haply.read.call_args.args[0]["state"]["sequence"] == 2
    robot["state"]["sequence"] = 3
    await app.action("haply.read", {"id": robot["id"], "enabled": True})
    assert app.haply.read.call_args.args[0]["state"]["sequence"] == 3
    robot.update(owner="Other", owner_id="another-session")
    await app.action("haply.read", {"id": robot["id"], "enabled": True})
    assert app.haply.read.call_args.args[1]["enabled"] is False


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize("workspace", [False, True])
def test_native_haply_layout_and_selection_stop(
    monkeypatch, virtual_display, robot, scale, workspace
):
    import tkinter as tk

    from telesurgery.controller.haply import NAME
    from telesurgery.controller.window import Window

    robot.update(name="MIRA", simulation=True)
    if workspace:
        robot["controls"]["mira_follow"] = {"version": 1}
    reader = Mock()
    reader.sample.return_value = (None, "Calibrate the Inverse3.")
    monkeypatch.setattr("telesurgery.controller.window.Gamepads", lambda: None)
    monkeypatch.setattr("telesurgery.controller.window.Haply", lambda: reader)
    monkeypatch.setattr("telesurgery.controller.window.haply_available", lambda: True)
    monkeypatch.setattr(Window, "tick", lambda self: None)
    root = tk.Tk(screenName=virtual_display)
    root.tk.call("tk", "scaling", scale * 96 / 72)
    monkeypatch.setattr(root, "winfo_screenheight", lambda: 4000)
    client = SimpleNamespace(action=Mock(side_effect=AssertionError("No robot commands")))
    selection = {"name": NAME, "ordinal": 0, "count": 1}
    window = Window(root, client, input_device=selection)
    try:
        now = time.monotonic()
        window.poll_devices(now)
        assert window.restore_input == selection  # Status arrives asynchronously at startup.
        window.update_status(
            {
                "role": "surgeon",
                "session": {"id": "me", "status": "approved", "robot": True, "robots": [robot]},
            },
            now,
        )
        window.poll_devices(now)
        assert window.device.get() == NAME
        window.feedback()
        root.update()
        assert window.haply is reader
        assert window.message.cget("text") == "Calibrate the Inverse3."
        reader.sample.return_value = (None, "")
        window.feedback()
        assert window.message.cget("text") == "Acquire control to enable input."
        assert window.haply_status.cget("text") == "Paused · Left arm"
        assert [label.cget("text") for label in window.haply_position.values] == [
            "100.0",
            "200.0",
            "300.0",
        ]
        assert not window.mode_choice.winfo_viewable()
        assert window.body.winfo_width() >= window.body.winfo_reqwidth()
        assert len(window.sliders) == 3
        assert not any(key in window.keys for key in "zxnm")
        assert set(window.grippers) == {"left", "right"}
        assert window.reset_button.winfo_ismapped()
        assert window.home.winfo_x() < window.reset_button.winfo_x() < window.stop_button.winfo_x()
        assert window.stop_button.icon == "stop"
        window.control.owned = window.selected  # Preview an explicitly acquired controller.
        window.reset_scene()
        assert window.pending_reset and window.haply_input.paused
        window.stop()
        assert not window.pending_reset
        window.haply_input.paused = False
        window.stop()
        assert window.haply_input.paused
        monkeypatch.setattr("telesurgery.controller.window.haply_available", lambda: False)
        window.poll_devices(now + 2)
        assert window.device.current() == 0
        reader.close.assert_called_once()
        client.action.assert_not_called()
    finally:
        window.control.owned = None
        window.shutdown()
        root.destroy()


@pytest.mark.parametrize("robot_kind", ["franka-sim", "franka", "versius-sim", "future-robot"])
@pytest.mark.parametrize(
    ("change", "kind", "axis", "sign"),
    [
        ({"position": (0.02, 0, 0)}, "translation", 1, -1),
        ({"position": (0, 0.02, 0)}, "translation", 0, 1),
        ({"position": (0, 0, 0.02)}, "translation", 2, 1),
        ({"angles": (10, 0)}, "rotation", 0, -1),
        ({"angles": (0, 10)}, "rotation", 2, -1),
    ],
)
def test_franka_pen_pose_uses_bounded_cartesian_jog(robot, change, kind, axis, sign, robot_kind):
    from telesurgery.controller.haply import CartesianHaply, supports

    robot = {
        **robot,
        "kind": robot_kind,
        "controls": {
            "groups": {"joints": 7},
            "cartesian": {"linear_speed_m_s": 0.1, "angular_speed_deg_s": 30.0},
            "speed_deg_s": {"min": 0.1, "max": 20},
        },
        "state": {
            "tool_pose": {
                "position_m": [0.5, 0, 0.3],
                "orientation_matrix": [[-1, 0, 0], [0, 1, 0], [0, 0, -1]],
            }
        },
    }
    assert supports(robot)
    driver = Driver(robot)
    driver.mapper = CartesianHaply()
    driver.resume()
    mode, command = driver.tick(**change)
    assert mode == "jog"
    assert command[kind][axis] * sign > 0
    assert all(math.hypot(*v) <= 1.000001 for v in command.values())
    assert driver.mapper.arm == "hand"
    assert driver.mapper.position_mm(driver.state) == [500, 0, 300]
    driver.state.update(stopping=True, stop_reason="released")
    assert driver.tick() is None
    assert not driver.mapper.paused
    driver.state.update(stopping=False, stop_reason=None)
    assert driver.tick()[0] == "jog"
    assert driver.tick(buttons=frozenset("a")) == ("release", {})
    assert driver.tick(buttons=frozenset()) == ("release", {})
    assert driver.mapper.paused

    driver.resume()
    driver.tick(buttons=frozenset("b"))
    driver.tick(buttons=frozenset())
    assert driver.mapper.arm == "hand" and not driver.mapper.paused
    driver.state.update(stopping=True, stop_reason="Physics feedback stale")
    assert driver.tick() == ("release", {})
    assert driver.mapper.paused and driver.mapper.error == "Physics feedback stale"
