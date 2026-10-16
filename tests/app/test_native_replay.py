# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native replay shares admission, delayed feedback and cancellation with the browser."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from telesurgery.controller.client import Control
from telesurgery.controller.haply import NAME as HAPLY_NAME
from telesurgery.controller.native_replay import NativeReplay, recording_for
from telesurgery.controller.replay import Catalog
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.registry import adapter_type


def robot(kind="franka"):
    role = "left" if kind == "versius" else kind
    return {
        "id": f"node:{role}",
        "name": kind.title(),
        "kind": f"{kind}-sim",
        "simulation": True,
        "status": "online",
        "controls": controls(adapter_type(f"{kind}-sim")({"uri": "unused"}), {}),
        "state": {"sequence": 1, "control_active": False},
    }


def reply(**changes):
    return {
        "feedback_paced": True,
        "elapsed": 0,
        "request": None,
        "done": False,
        "run": "current-run",
        "state": {"sequence": 2},
        **changes,
    }


def pump(control, replay, until, timeout=3):
    deadline = time.monotonic() + timeout
    while not until() and time.monotonic() < deadline:
        now = time.monotonic()
        control.poll(now)
        replay.poll(now)
        time.sleep(0.005)
    assert until()


@pytest.fixture
def playback():
    calls = []
    read = Mock(return_value=reply())
    other = Mock(return_value={"sequence": 3})

    def action(method, params):
        calls.append((method, params))
        return read() if method == "replay.read" else other(method, params)

    client = SimpleNamespace(action=action)
    control = Control(client)
    control.owned = robot()["id"]
    replay = NativeReplay(client, control)
    record = recording_for(Catalog().list(), robot(), "keyboard")
    assert replay.start(robot(), record)
    try:
        yield control, replay, calls, read, other
    finally:
        replay.close()
        control.close()


def test_native_replay_waits_sends_exact_run_and_holds_without_releasing(playback):
    control, replay, calls, read, _ = playback
    read.side_effect = [
        reply(waiting=True),
        reply(waiting_peer=True),
        reply(
            waiting_peer=True, waiting_reason="Holding needle · waiting for right arm to grasp it"
        ),
        reply(request=("grip", {"hand": -0.4}), speed_deg_s=8),
        reply(request=("release", {}), done=True, elapsed=12),
    ]
    pump(control, replay, lambda: replay.status == "Waiting for the other surgeon…")
    pump(control, replay, lambda: replay.status == "Waiting at handoff checkpoint…")
    pump(
        control,
        replay,
        lambda: replay.status == "Holding needle · waiting for right arm to grasp it",
    )
    pump(control, replay, lambda: not replay.busy and control.ready)
    assert replay.status == "Replay complete"
    moves = [params for method, params in calls if method == "robot.move"]
    assert moves == [
        {
            "id": "node:franka",
            "mode": "grip",
            "command": {"velocity": {"hand": -0.4}},
            "speed_deg_s": 8,
            "replay": True,
            "replay_run": "current-run",
        }
    ]
    assert any(method == "robot.hold" for method, _ in calls)
    assert not any(method in {"robot.release", "replay.cancel"} for method, _ in calls)
    assert control.owned == "node:franka"


def test_native_mira_replay_keeps_input_bounds_without_unsupported_speed_parameter(playback):
    control, replay, calls, read, _ = playback
    replay.stop()
    pump(control, replay, lambda: not replay.busy and control.ready)
    fixture = robot("mira")
    control.owned = fixture["id"]
    assert replay.start(fixture, recording_for(Catalog().list(), fixture, "keyboard"))
    read.side_effect = [
        reply(request=("cartesian", {"right": [0.1, 0, 0, 0, 0]}), speed_deg_s=8),
        reply(done=True),
    ]
    pump(control, replay, lambda: not replay.busy and control.ready)
    moves = [params for method, params in calls if method == "robot.move"]
    assert len(moves) == 1
    assert moves[0]["command"] == {"right": [0.1, 0, 0, 0, 0]}
    assert "speed_deg_s" not in moves[0]
    assert replay.status == "Replay complete"


@pytest.mark.parametrize("paced", [True, False])
def test_native_replay_heartbeats_continue_during_slow_feedback(playback, paced):
    control, replay, calls, read, _ = playback

    def slow():
        time.sleep(0.35)
        return reply(feedback_paced=paced, done=True)

    read.side_effect = slow
    pump(control, replay, lambda: not replay.busy)
    assert sum(method == "replay.heartbeat" for method, _ in calls) >= 3
    assert replay.status == (
        "Replay complete" if paced else "Replay stopped · timed replay response delayed"
    )


def test_native_stop_discards_late_read_and_cancels_before_it_returns(playback):
    control, replay, calls, read, _ = playback
    entered, unblock = threading.Event(), threading.Event()

    def slow():
        entered.set()
        assert unblock.wait(2)
        return reply(request=("jog", {"joints": [1] * 7}))

    read.side_effect = slow
    try:
        pump(control, replay, entered.is_set)
        replay.stop()
        pump(control, replay, lambda: any(m == "replay.cancel" for m, _ in calls))
        assert not replay.start(robot(), recording_for(Catalog().list(), robot(), "keyboard"))
        unblock.set()
        pump(control, replay, lambda: not replay.busy)
        assert not any(m == "robot.move" for m, _ in calls)
        assert control.owned == "node:franka"
    finally:
        unblock.set()


def test_native_stop_cancels_again_after_a_late_start(playback):
    control, replay, calls, _, other = playback
    entered, unblock = threading.Event(), threading.Event()

    def action(method, _):
        if method == "replay.start":
            entered.set()
            assert unblock.wait(2)
        return True

    other.side_effect = action
    try:
        pump(control, replay, entered.is_set)
        replay.stop()
        pump(control, replay, lambda: any(m == "replay.cancel" for m, _ in calls))
        unblock.set()
        pump(control, replay, lambda: not replay.busy)
        assert sum(m == "replay.cancel" for m, _ in calls) == 2
        assert not any(m in {"replay.read", "robot.move"} for m, _ in calls)
    finally:
        unblock.set()


def test_native_stop_holds_after_delayed_motion_acknowledgement(playback):
    control, replay, calls, read, other = playback
    entered, unblock = threading.Event(), threading.Event()
    read.return_value = reply(request=("jog", {"joints": [1] * 7}))

    def action(method, _):
        if method == "robot.move":
            entered.set()
            assert unblock.wait(2)
        return {"sequence": 3}

    other.side_effect = action
    try:
        pump(control, replay, entered.is_set)
        replay.stop()
        pump(control, replay, lambda: any(m == "replay.cancel" for m, _ in calls))
        unblock.set()
        pump(control, replay, lambda: not replay.busy and control.ready)
        assert sum(m == "robot.move" for m, _ in calls) == 1
        assert any(m == "robot.hold" for m, _ in calls)
        assert control.owned == "node:franka"
    finally:
        unblock.set()


def test_native_read_failure_retains_reason_and_control(playback):
    control, replay, calls, read, _ = playback
    read.side_effect = RuntimeError("The other surgeon stopped replay")
    pump(control, replay, lambda: not replay.busy)
    assert replay.status == "Replay stopped · The other surgeon stopped replay"
    assert control.owned == "node:franka"
    assert not any(m == "robot.move" for m, _ in calls)


@pytest.mark.parametrize("kind", ["mira", "franka", "versius"])
@pytest.mark.parametrize("device", ["keyboard", "gamepad", "haply"])
def test_native_replay_toolbar_matches_robot_and_input(monkeypatch, virtual_display, kind, device):
    import tkinter as tk

    from telesurgery.controller.window import Window

    monkeypatch.setattr("telesurgery.controller.window.Gamepads", lambda: None)
    monkeypatch.setattr(Window, "tick", lambda self: None)
    root = tk.Tk(screenName=virtual_display)
    client = SimpleNamespace(action=Mock(return_value=True))
    window = Window(root, client)
    try:
        fixture = robot(kind)
        window.update_status(
            {
                "role": "surgeon",
                "replays": Catalog().list(),
                "session": {"id": "me", "status": "approved", "robot": True, "robots": [fixture]},
            },
            time.monotonic(),
        )
        window.control.owned = fixture["id"]
        window.device.configure(values=["Keyboard", "Test gamepad", HAPLY_NAME])
        window.device.current({"keyboard": 0, "gamepad": 1, "haply": 2}[device])
        window.build_controls()
        window.feedback()
        root.update()
        assert window.replay_button.winfo_ismapped()
        assert window.replay_button.icon == "replay"
        assert (
            window.home.winfo_x()
            < window.reset_button.winfo_x()
            < window.replay_button.winfo_x()
            < window.stop_button.winfo_x()
        )
        assert window.replay_recording()["id"] == f"{kind}/{device}"
        hint = {
            "mira": "Reset both arms and the needle.",
            "franka": "Reset the arm and probe to their starting positions.",
            "versius": "Reset all four arms and the needle.",
        }[kind]
        assert window.reset_button.tooltip.text == hint
        if kind == "versius":
            fixture["reset_scene_blocked"] = "Release control of all other arms before resetting."
            window.feedback()
            assert not window.reset_button.enabled
            assert window.reset_button.tooltip.text == hint + " " + fixture["reset_scene_blocked"]
            window.reset_scene()
            assert not window.pending_reset
            fixture["reset_scene_blocked"] = ""
            window.feedback()
            assert window.reset_button.enabled
        window.start_replay()
        assert window.replay.active and not window.available()
        window.feedback()
        root.update()
        assert window.replay_status.cget("text") == "Preparing replay…"
        window.replay.input = {
            "device": device,
            "keys": ["w"],
            "axes": [1, 0, 0, 0],
            "buttons": [4, 3],
        }
        window.feedback()
        if device == "keyboard":
            assert window.keys["w"].pressed and not window.keys["w"].enabled
        elif device == "gamepad":
            assert window.gamepad_active(("axis", 0))
            assert window.gamepad_active(("button", 3, 0))
        monkeypatch.setattr(window, "focused", lambda: False)
        monkeypatch.setattr(window, "editing", lambda: False)
        window.check_focus()
        window.drive(time.monotonic())
        assert window.replay.active  # Keep replaying while watching Holoviz.
        if device == "keyboard":
            window.key_down(SimpleNamespace(keysym="Escape"))
        elif device == "gamepad":
            window.device.current(0)
            window.select_device()
        else:
            root.withdraw()
            root.update()
        assert not window.replay.active
        assert window.control.owned == fixture["id"]
        assert not any(c.args[0] == "robot.move" for c in client.action.call_args_list)
        fixture["simulation"] = False
        assert window.replay_recording() is None
    finally:
        window.control.owned = None
        window.shutdown()
        root.destroy()
