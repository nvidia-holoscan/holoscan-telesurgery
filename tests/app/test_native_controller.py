# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native input shares browser mappings, release normalization and bounded requests."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telesurgery.controller.client import Client, Control
from telesurgery.controller.input import Inputs
from telesurgery.controller.widgets import Button
from telesurgery.server.application import Application
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import (
    FrankaSimulation,
    MiraSimulation,
    VersiusSimulation,
)


def robot(kind):
    adapter = {"mira": MiraSimulation, "franka": FrankaSimulation, "versius": VersiusSimulation}[
        kind
    ]({"uri": "unused"})
    if kind == "franka":
        adapter.grippers = ("hand",)
    return {
        "id": kind,
        "name": kind.title(),
        "status": "online",
        "controls": controls(adapter, {"motion_enabled": True}),
        "state": {"sequence": 1},
    }


@pytest.mark.parametrize("hold", [False, True])
def test_button_release_survives_feedback_refresh(hold):
    button = Button.__new__(Button)
    button.enabled, button.pressed, button.down = True, False, False
    button.text = "Home"
    button.draw = button.focus_set = Mock()
    button.command = Mock()
    button.hold = Mock() if hold else None
    button.press(None)
    for _ in range(10):
        button.update_state(enabled=True)
    assert button.pressed
    # A stop or unavailable-state repaint must still allow a held input to release.
    if hold:
        button.update_state(enabled=False, pressed=False)
    button.release(None)
    button.release(None)
    if hold:
        assert [call.args for call in button.hold.call_args_list] == [(True,), (False,)]
        button.command.assert_not_called()
    else:
        button.command.assert_called_once_with()


def test_disabled_button_does_not_execute_pending_click():
    button = Button.__new__(Button)
    button.enabled, button.pressed, button.down = True, False, False
    button.text, button.hold = "Home", None
    button.draw = button.focus_set = Mock()
    button.command = Mock()
    button.press(None)
    button.update_state(enabled=False)
    button.release(None)
    button.command.assert_not_called()
    assert not button.down


@pytest.mark.parametrize("kind", ["mira", "franka", "versius"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_keyboard_repeat_pairs_and_stopped_hold(kind, interrupted):
    inputs = Inputs(robot(kind))
    inputs.grip_percent = 100
    key = inputs.keyboard
    key.press("z", 0)
    requests = []
    for i in range(100):
        now = i * 0.05
        if interrupted and i == 50:
            inputs.halt()
        key.release("z", now)
        key.poll(now + 0.008)
        assert not key.press("z", now + 0.009)
        result = inputs.from_keyboard(now + 0.01)
        if result:
            requests.append(result)
    assert len(requests) == (50 if interrupted else 100)
    group = "left" if kind == "mira" else "hand"
    assert all(mode == "grip" and command[group] == -0.5 for mode, command in requests)
    key.release("z", 5)
    assert inputs.from_keyboard(5.02) == (None if interrupted else ("release", {}))
    assert key.press("z", 5.03)
    assert inputs.from_keyboard(5.06)[0] == "grip"


@pytest.mark.parametrize("kind", ["mira", "franka", "versius"])
def test_joint_tap_then_continuous_hold_and_real_release(kind):
    inputs = Inputs(robot(kind))
    inputs.mode = "joints"
    key = inputs.keyboard
    key.press("q", 0)
    assert inputs.from_keyboard(0)[0] == "step"
    assert inputs.from_keyboard(0.1) is None
    assert inputs.from_keyboard(0.44) is None
    assert inputs.from_keyboard(0.46)[0] == "jog"
    assert inputs.from_keyboard(0.51)[0] == "jog"
    key.release("q", 0.52)
    assert inputs.from_keyboard(0.54) == ("release", {})
    assert inputs.from_keyboard(0.8) is None


def test_versius_all_eight_joints_and_cartesian_mapping():
    inputs = Inputs(robot("versius"))
    inputs.mode = "joints"
    assert inputs.bindings()["i"] == ("joints", 7, 1)
    assert inputs.bindings()["k"] == ("joints", 7, -1)
    inputs.mode = "cartesian"
    inputs.keyboard.press("w", 0)
    inputs.keyboard.press("left", 0)
    mode, command = inputs.from_keyboard(0)
    assert mode == "jog"
    assert command == {"translation": [1, 0, 0], "rotation": [1, 0, 0]}


def test_mira_tool_scales_and_bounds_xyz():
    inputs = Inputs(robot("mira"))
    inputs.mode = "mira-tool"
    for key in "qweu":
        inputs.keyboard.press(key, 0)
    mode, command = inputs.from_keyboard(0)
    assert mode == "cartesian"
    assert all(v > 0 for v in command["left"][:3])
    assert command["right"][0] > 0
    assert (
        sum(v * v for v in command["left"][:3])
        <= inputs.controls["mira_cartesian"]["linear_step_mm"] ** 2
    )


@pytest.mark.parametrize("kind", ["mira", "franka", "versius"])
def test_gamepad_rearm_home_hold_and_grip(kind):
    inputs = Inputs(robot(kind))
    state = {"grippers": {"hand": 1, "left": 1, "right": 1}}
    neutral = [0] * 4
    assert inputs.from_gamepad(neutral, set(), state, 0) is None
    buttons = {4} if kind == "mira" else set()
    assert inputs.from_gamepad([0, -1, 0, 0], buttons, state, 0.1)[0] == "jog"
    inputs.halt()
    assert inputs.from_gamepad([0, -1, 0, 0], buttons, state, 0.2) is None
    assert inputs.from_gamepad(neutral, set(), state, 0.3) is None
    grip_buttons = {4, 14} if kind == "mira" else {2}
    assert inputs.from_gamepad(neutral, grip_buttons, state, 0.4)[0] == "grip"
    inputs.halt()
    assert inputs.from_gamepad(neutral, grip_buttons, state, 0.5) is None
    inputs.from_gamepad(neutral, set(), state, 0.6)
    assert inputs.from_gamepad(neutral, {9}, state, 0.7) is None
    assert inputs.from_gamepad(neutral, {9}, state, 1.69) is None
    assert inputs.from_gamepad(neutral, {9}, state, 1.71) == ("home", {})
    assert inputs.from_gamepad(neutral, {9}, state, 3) is None
    inputs.from_gamepad(neutral, set(), state, 3.1)
    inputs.from_gamepad(neutral, {9}, state, 3.2)
    inputs.from_gamepad(neutral, {16}, state, 4)
    assert inputs.from_gamepad(neutral, {16}, state, 5.1) is None


def test_grip_and_cartesian_keepalive_alternate_and_stop_zero_axis():
    inputs = Inputs(robot("versius"))
    inputs.from_gamepad([0] * 4, set(), {"grippers": {"hand": 1}}, 0)
    requests = [
        inputs.from_gamepad([0, -1, 0, 0], {2}, {"grippers": {"hand": 0.8}}, (i + 1) * 0.05)
        for i in range(8)
    ]
    assert [r[0] for r in requests] == ["grip", "jog"] * 4
    assert inputs.from_gamepad([0] * 4, set(), {"grippers": {"hand": 0.8}}, 0.45)[0] == "grip"
    mode, value = inputs.from_gamepad([0] * 4, set(), {"grippers": {"hand": 0.8}}, 0.5)
    assert mode == "jog" and not any(value["translation"])


def test_slow_reply_cannot_queue_motion_and_release_follows_inflight():
    accepted, reply = threading.Event(), threading.Event()
    calls = []

    def action(method, params):
        calls.append((method, params))
        if method == "robot.move":
            accepted.set()
            assert reply.wait(2)
        return {"sequence": len(calls)}

    control = Control(SimpleNamespace(action=action))
    try:
        assert control.move("robot", "grip", {"hand": -0.5}, 10)
        assert accepted.wait(2)
        for _ in range(50):
            assert not control.move("robot", "jog", {"joints": [1]}, 10)
        control.stop()
        reply.set()
        deadline = time.monotonic() + 2
        while (control.pending or control.owned) and time.monotonic() < deadline:
            control.poll(time.monotonic())
            time.sleep(0.001)
        assert [method for method, _ in calls] == ["robot.move", "robot.release"]
        assert calls[0][1]["command"] == {"velocity": {"hand": -0.5}}
        assert control.ready and control.owned is None
    finally:
        reply.set()
        control.close()


def test_native_does_not_claim_observed_same_session_ownership():
    calls = []
    control = Control(SimpleNamespace(action=lambda *args: calls.append(args)))
    try:
        assert (
            control.feedback({"id": "robot", "owner_id": "same-session", "state": {"sequence": 3}})[
                "sequence"
            ]
            == 3
        )
        control.poll(100)
        control.stop()
        control.poll(101)
        assert not calls
    finally:
        control.close()


@pytest.mark.asyncio
async def test_native_launch_requires_approved_robot_access():
    service = SimpleNamespace(
        role="surgeon",
        remote_status={"status": "approved", "robot": False},
        controller=SimpleNamespace(open=AsyncMock()),
        controller_server="http://127.0.0.1:8002",
        controller_certificate=None,
    )
    with pytest.raises(PermissionError):
        await Application.action(service, "controller.open", {})
    service.remote_status.update(robot=True, robots=[{"id": "robot"}])
    await Application.action(service, "controller.open", {"id": "robot"})
    service.controller.open.assert_awaited_once_with("http://127.0.0.1:8002", "robot", None, None)
    with pytest.raises(ValueError):
        await Application.action(service, "controller.open", {"id": "missing"})


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/local", "http://user:password@host", "http://host/path", "http://host?query=1"],
)
def test_native_rejects_non_dashboard_urls(url):
    with pytest.raises(ValueError):
        Client(url)
