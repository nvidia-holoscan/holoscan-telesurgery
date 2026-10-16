# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import threading

import pytest
from telesurgery_core.transport.rpc import RpcClient
from telesurgery_robots.simulation.state import SimRobot


def test_controller_disconnect_does_not_wait_for_unresponsive_close_handshake():
    import base64
    import hashlib
    import socket
    import time

    finished = threading.Event()
    with socket.create_server(("127.0.0.1", 0)) as server:

        def vendor():
            with server.accept()[0] as connection:
                headers = b""
                while b"\r\n\r\n" not in headers:
                    headers += connection.recv(4096)
                key = next(
                    line.split(b":", 1)[1].strip()
                    for line in headers.splitlines()
                    if line.lower().startswith(b"sec-websocket-key:")
                )
                accept = base64.b64encode(
                    hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
                )
                connection.sendall(
                    b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n"
                )
                finished.wait(5)  # Vendor never acknowledges the close frame.

        thread = threading.Thread(target=vendor)
        thread.start()
        try:
            client = RpcClient(f"ws://127.0.0.1:{server.getsockname()[1]}", timeout=0.1)
            started = time.monotonic()
            client.close()
            assert time.monotonic() - started < 1
            assert client.socket.sock is None
        finally:
            finished.set()
            thread.join(timeout=2)


@pytest.mark.parametrize("reject", [False, True, {"code": -32602, "message": "Franka is stopping"}])
def test_rpc_ids_responses_and_failure_without_retry(reject):
    pytest.importorskip("websocket")
    serve = pytest.importorskip("websockets.sync.server").serve
    observed = []

    def handle(socket):
        request = json.loads(socket.recv())
        observed.append(request)
        reply = {"jsonrpc": "2.0", "id": request["id"]}
        reply["error" if reject else "result"] = reject if isinstance(reject, dict) else "fixture"
        socket.send(json.dumps(reply))

    with serve(handle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        client = RpcClient(f"ws://127.0.0.1:{server.socket.getsockname()[1]}")
        try:
            request = {"method": "get_state", "params": {}}
            if reject:
                reason = reject["message"] if isinstance(reject, dict) else "fixture"
                with pytest.raises(RuntimeError, match=f"^Controller rejected request: {reason}$"):
                    client.send(request)
            else:
                assert client.send(request) == "fixture"
        finally:
            client.close()
            server.shutdown()
            thread.join(timeout=2)
    assert len(observed) == 1
    assert observed[0]["id"] == 1


def test_sim_rpc_updates_both_arms_and_rejects_partial_bad_request():
    robot = SimRobot()
    original = {arm: list(pose) for arm, pose in robot.pose.items()}
    with pytest.raises(ValueError):
        robot.apply(
            {
                "method": "set_mira_cartesian_delta",
                "params": {"left": [1, 0, 0, 0, 0], "right": [float("nan"), 0, 0, 0, 0]},
            }
        )
    assert robot.pose == original
    robot.apply(
        {
            "method": "set_mira_cartesian_delta",
            "params": {"left": [1, 0, 0, 0, 0], "right": [0, 1, 0, 0, 0]},
        }
    )
    assert robot.pose["left"][0] == pytest.approx(original["left"][0] + 1)
    assert robot.pose["right"][1] == pytest.approx(original["right"][1] - 1)


def test_physical_mira_uses_measured_position_and_does_not_replay_motion():
    from telesurgery_robots.mira.adapter import Mira

    serve = pytest.importorskip("websockets.sync.server").serve
    observed = []
    measured = {
        "left": [10.0, 20.0, 30.0, 40.0, 5.0, 0.0],
        "right": [11.0, 21.0, 31.0, 41.0, 6.0, 0.0],
    }

    def handle(socket):
        socket.send(
            json.dumps({"jsonrpc": "2.0", "method": "backend_identity", "params": "cart", "id": 0})
        )
        for text in socket:
            request = json.loads(text)
            observed.append(request)
            if request["method"] == "get_mira_pose":
                # Shared vendor replies and collision events must not become state.
                socket.send(json.dumps({"jsonrpc": "2.0", "id": -1, "result": None}))
                socket.send(
                    json.dumps(
                        {"jsonrpc": "2.0", "method": "boundary_collision_event", "params": {}}
                    )
                )
                socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": measured}))

    with serve(handle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        robot = Mira(f"ws://127.0.0.1:{server.socket.getsockname()[1]}")
        try:
            for _ in range(2):
                state = robot.send(
                    {
                        "method": "set_mira_joint_delta",
                        "params": {"left": [0.2, 0, 0, 0, 0], "right": [0, 0, 0, 0, 0]},
                    }
                )
                assert state["joints_deg"] == measured
            movements = [r for r in observed if r["method"] == "set_mira_pose"]
            assert len(movements) == 2
            assert all(r["params"]["left"][0] == pytest.approx(10.2) for r in movements)
            assert all(r["params"]["left"][4:] == [5.0, 0.0] for r in movements)
            assert all("id" not in r for r in movements)
            count = len(observed)
            with pytest.raises(ValueError):
                robot.send(
                    {
                        "method": "set_mira_joint_delta",
                        "params": {"left": [1.01, 0, 0, 0, 0], "right": [0, 0, 0, 0, 0]},
                    }
                )
            assert len(observed) == count
            robot.send({"method": "hold"})
            assert [r for r in observed if r["method"] == "set_mira_pose"][-1]["params"] == measured
        finally:
            robot.close()
            server.shutdown()
            thread.join(timeout=2)


def test_physical_mira_is_read_only_until_enabled():
    from telesurgery_robots.mira.adapter import MiraAdapter
    from telesurgery_runtime.application.robots import Controller

    spec = {"kind": "mira", "uri": "ws://127.0.0.1:1"}
    robot = Controller(MiraAdapter(spec), lambda: spec, lambda: 0)
    with pytest.raises(PermissionError, match="supervised validation"):
        robot.prepare("token")
    assert robot.adapter.client.client is None


def test_disabling_physical_motion_holds_active_lease_without_another_jog():
    import time

    from telesurgery_runtime.application.robots import Controller

    observed = []

    class Device:
        simulation = False
        groups = {"left": 4, "right": 4}
        max_step_deg = 0.4

        def read(self):
            observed.append("get_state")
            return {}

        def hold(self):
            observed.append("hold")
            return {}

        def close(self):
            pass

    spec = {"motion_enabled": True}
    robot = Controller(Device(), lambda: spec, lambda: 0)
    robot.prepare("owner")
    spec["motion_enabled"] = False
    with pytest.raises(PermissionError, match="disabled"):
        robot.move("owner", 1, {"left": [0.1, 0, 0, 0], "right": [0] * 4}, time.time())
    assert observed == ["get_state", "hold"]
    assert robot.token is None
    robot.close()
    assert observed == ["get_state", "hold"]


def test_physical_mira_home_grippers_and_stop_use_vendor_commands(monkeypatch):
    import copy
    import time

    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.mira.adapter import MiraAdapter
    from telesurgery_robots.mira.poses import MIRA_HOME
    from telesurgery_runtime.application.robots import Controller

    serve = pytest.importorskip("websockets.sync.server").serve
    measured = {"left": [10, 20, 30, 40, 5, 1000], "right": [11, 21, 31, 41, 6, 1351.8]}
    original = copy.deepcopy(measured)
    observed = []
    homed = True

    def handle(socket):
        for text in socket:
            request = json.loads(text)
            observed.append(request)
            if request["method"] == "get_mira_pose":
                socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": measured}))
            elif request["method"] in {"set_left_gripper", "set_right_gripper"}:
                if not homed:
                    socket.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": request["id"],
                                "error": {"code": 11, "message": "Tools not homed"},
                            }
                        )
                    )
                # The vendor does not reply on success. A later query completes
                # the round trip; a rejection must not be swallowed as a broadcast.

    with serve(handle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        spec = {"uri": f"ws://127.0.0.1:{server.socket.getsockname()[1]}", "motion_enabled": True}
        adapter = MiraAdapter(spec)
        controller = Controller(adapter, lambda: spec, lambda: 0)
        try:
            assert controls(adapter, spec)["default_step_deg"] == 1
            assert controls(adapter, spec)["max_step_deg"] == 1
            with pytest.raises(PermissionError):
                controller.move("owner", 1, {}, time.time(), mode="home")
            controller.prepare("owner")
            controller.move("owner", 1, {"left": [1, 0, 0, 0, 0], "right": [0] * 5}, time.time())
            pose = [r for r in observed if r["method"] == "set_mira_pose"][-1]["params"]
            assert pose == {"left": [11, 20, 30, 40, 5, 1000], "right": original["right"]}
            state = controller.move("owner", 2, {}, time.time(), mode="home")
            assert state["home_active"]
            for arm in measured:
                assert state["targets_deg"][arm] == [*MIRA_HOME, 0, 0]
                assert [r for r in observed if r["method"] == f"set_{arm}_gripper"][-1][
                    "params"
                ] == 0
            assert [r for r in observed if r["method"] == "set_mira_roll"][-1]["params"] == {
                "left": 0,
                "right": 0,
            }
            writes = [r for r in observed if r["method"].startswith("set_")]
            with pytest.raises(ValueError, match="moving home"):
                adapter.home()
            assert [r for r in observed if r["method"].startswith("set_")] == writes
            with pytest.raises(ValueError, match="moving home"):
                adapter.jog({"left": [1, 0, 0, 0, 0], "right": [0] * 5})
            with pytest.raises(ValueError, match="moving home"):
                adapter.grip({"velocity": {"left": 0.2}})
            controller.release()
            assert not adapter.read()["home_active"]
            assert [r for r in observed if r["method"] == "set_mira_pose"][-1]["params"] == original
            assert [r for r in observed if r["method"] == "set_mira_roll"][-1]["params"] == {
                arm: pose[4] for arm, pose in original.items()
            }
            for arm, maximum in (("left", 1150), ("right", 1350)):
                assert [r for r in observed if r["method"] == f"set_{arm}_gripper"][-1][
                    "params"
                ] == pytest.approx(min(1, original[arm][5] / maximum))
            adapter.home()
            for arm in measured:
                measured[arm][:4] = MIRA_HOME
            assert adapter.read()["home_active"]  # Arms alone do not complete Home.
            for arm in measured:
                measured[arm][4] = 0
            assert adapter.read()["home_active"]  # Wait for the jaws too.
            for arm in measured:
                measured[arm][5] = 0
            assert adapter.read()["home_active"]  # Require stable feedback after arrival.
            time.sleep(0.13)
            assert adapter.read()["home_active"]
            time.sleep(0.13)
            assert not adapter.read()["home_active"]
            for bad in (
                {},
                {"left": 2},
                {"left": True},
                {"left": float("nan")},
                {"unknown": 1},
                {"left": 1, "right": 1},
            ):
                count = len(observed)
                with pytest.raises(ValueError):
                    adapter.grip(bad)
                assert len(observed) == count
            from types import SimpleNamespace

            clock = [100.0]
            monkeypatch.setattr(
                "telesurgery_robots.mira.gripper.time", SimpleNamespace(monotonic=lambda: clock[0])
            )
            for arm in measured:
                measured[arm][4:] = original[arm][4:]
            homed = False
            adapter.grip({"velocity": {"left": -0.2}})
            clock[0] += 0.05
            with pytest.raises(RuntimeError, match="Tools not homed"):
                adapter.read()
            assert not adapter.client.grip.rates
            homed = True
            adapter.read()  # Recovery sends only a measured hold, never the rejected target.
            assert [r for r in observed if r["method"] == "set_left_gripper"][-1][
                "params"
            ] == pytest.approx(1000 / 1150)
            for arm in ("left", "right"):
                adapter.grip({"velocity": {arm: -0.2}})
                clock[0] += 0.05
                adapter.read()
                target = [r for r in observed if r["method"] == f"set_{arm}_gripper"][-1]["params"]
                assert 0 <= target < min(1, measured[arm][5] / (1150 if arm == "left" else 1350))
                adapter.hold()
                assert not adapter.client.grip.rates
                assert [r for r in observed if r["method"] == f"set_{arm}_gripper"][-1][
                    "params"
                ] == pytest.approx(min(1, measured[arm][5] / (1150 if arm == "left" else 1350)))
            assert all(
                "force_" not in r["method"] and r["method"] != "request_home_tools"
                for r in observed
            )
            measured["left"][0] = 0
            adapter.home()
            monkeypatch.setattr(
                "telesurgery_robots.mira.adapter.time.monotonic",
                lambda: adapter.client.home_deadline + 1,
            )
            with pytest.raises(RuntimeError, match="timed out"):
                adapter.read()
            assert not adapter.read()["home_active"]
            assert [r for r in observed if r["method"] == "set_mira_pose"][-1]["params"] == measured
        finally:
            adapter.close()
            server.shutdown()
            thread.join(timeout=2)


def test_simulated_mira_grippers_are_independent_and_home_resets_them(monkeypatch):
    from types import SimpleNamespace

    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.adapters.simulation import FrankaSimulation, MiraSimulation

    clock = [100.0]
    monkeypatch.setattr(
        "telesurgery_robots.mira.gripper.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    sim = SimRobot()
    adapter = MiraSimulation({"uri": "unused"})
    adapter.client = sim
    sim.send = sim.apply
    assert controls(adapter, {})["grippers"] == ("left", "right")
    assert "grippers" not in controls(FrankaSimulation({"uri": "unused"}), {})
    before = adapter.read()["targets_deg"]
    adapter.grip({"velocity": {"left": 0.2, "right": 0.2}})
    for _ in range(10):
        clock[0] += 0.05
        state = adapter.grip({"velocity": {"left": 0.2, "right": 0.2}})
    assert state["grippers"] == pytest.approx({"left": 0.1, "right": 0.1})
    for arm in before:
        assert state["targets_deg"][arm][:5] == before[arm][:5]
    # Measured jaw position, not a pending target, is used when releasing.
    sim.feedback = {"grippers_deg": {"left": 2.0, "right": -2.0}}
    state = adapter.hold()
    for arm in before:
        assert state["targets_deg"][arm][5] == sim.feedback["grippers_deg"][arm]
    clock[0] += 1
    assert adapter.read()["targets_deg"] == state["targets_deg"]
    adapter.grip({"velocity": {"left": 0.2, "right": 0.2}})
    assert adapter.home()["targets_deg"] == before
    assert not sim.grip.rates
    clock[0] += 0.1
    assert adapter.read()["targets_deg"] == before


def test_simulated_mira_home_waits_for_tools_and_stop_holds_measured_pose():
    from telesurgery_robots.mira.poses import MIRA_SIM_HOME

    sim = SimRobot()
    initial = {arm: list(pose) for arm, pose in sim.pose.items()}
    sim.feedback = {
        "joints_deg": {"left": [10, 20, 30, 40, 50], "right": [20, 30, 40, 50, -60]},
        "grippers_deg": {"left": 20, "right": -30},
    }
    state = sim.apply({"method": "set_home"})
    assert state["targets_deg"] == initial
    assert state["home_active"] and state["control_active"]
    with pytest.raises(ValueError, match="moving home"):
        sim.apply({"method": "jog_gripper", "params": {"velocity": {"left": 0.2}}})
    sim.apply({"method": "hold"})
    for arm in initial:
        assert sim.pose[arm] == [
            *sim.feedback["joints_deg"][arm],
            sim.feedback["grippers_deg"][arm],
        ]
    assert not sim.apply({"method": "get_state"})["home_active"]
    sim.apply({"method": "set_home"})
    for arm in initial:
        sim.feedback["joints_deg"][arm][:4] = MIRA_SIM_HOME[arm]
    assert sim.apply({"method": "get_state"})["home_active"]
    for arm in initial:
        sim.feedback["joints_deg"][arm][4] = 0
    assert sim.apply({"method": "get_state"})["home_active"]
    for arm in initial:
        sim.feedback["grippers_deg"][arm] = initial[arm][5]
    state = sim.apply({"method": "get_state"})
    assert not state["home_active"] and not state["control_active"]
    assert state["targets_deg"] == initial


@pytest.mark.parametrize(
    "failed_method", ["set_mira_roll", "set_left_gripper", "set_right_gripper"]
)
def test_physical_mira_failed_home_recovers_with_measured_holds(failed_method):
    from telesurgery_robots.mira.adapter import Mira

    serve = pytest.importorskip("websockets.sync.server").serve
    measured = {"left": [10, 20, 30, 40, 50, 500], "right": [11, 21, 31, 41, -60, 600]}
    observed = []
    reject = True

    def handle(socket):
        for raw in socket:
            request = json.loads(raw)
            observed.append(request)
            if request["method"] == "get_mira_pose":
                socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": measured}))
            elif reject and request["method"] == failed_method:
                socket.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request["id"],
                            "error": {"code": 11, "message": "Tools not homed"},
                        }
                    )
                )

    with serve(handle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        robot = Mira(f"ws://127.0.0.1:{server.socket.getsockname()[1]}")
        try:
            with pytest.raises(RuntimeError, match="Tools not homed"):
                robot.send({"method": "set_home"})
            assert robot.home_target is None and robot.home_holding
            reject = False
            observed.clear()
            assert not robot.state()["home_active"]
            writes = {r["method"]: r["params"] for r in observed if r["method"].startswith("set_")}
            assert writes == {
                "set_mira_pose": measured,
                "set_mira_roll": {arm: pose[4] for arm, pose in measured.items()},
                "set_left_gripper": pytest.approx(500 / 1150),
                "set_right_gripper": pytest.approx(600 / 1350),
            }
            observed.clear()
            robot.state()
            assert all(r["method"] == "get_mira_pose" for r in observed)
        finally:
            robot.close()
            server.shutdown()
            thread.join(timeout=2)


def test_physical_roll_is_bounded_measured_and_recovery_never_replays():
    from telesurgery_robots.mira.adapter import Mira

    serve = pytest.importorskip("websockets.sync.server").serve
    measured = {"left": [10, 20, 30, 40, 179.8, 900], "right": [11, 21, 31, 41, -179.8, 800]}
    writes = []
    reject = False

    def handle(socket):
        for text in socket:
            request = json.loads(text)
            if request["method"] == "get_mira_pose":
                socket.send(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": measured}))
            elif request["method"] == "set_mira_roll":
                writes.append(request["params"])
                if reject:
                    socket.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": request["id"],
                                "error": {"code": 11, "message": "Tool not ready"},
                            }
                        )
                    )

    with serve(handle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        robot = Mira(f"ws://127.0.0.1:{server.socket.getsockname()[1]}")
        jog = {
            "method": "set_mira_joint_delta",
            "params": {"left": [0, 0, 0, 0, 1], "right": [0, 0, 0, 0, -1]},
        }
        try:
            for _ in range(2):
                robot.send(jog)
            assert writes == [{"left": 180, "right": -180}] * 2
            robot.send({"method": "hold"})
            assert writes[-1] == {"left": 179.8, "right": -179.8}
            reject = True
            with pytest.raises(RuntimeError, match="Tool not ready"):
                robot.send(jog)
            assert robot.client is None and robot.roll_holding
            reject = False
            measured["left"][4], measured["right"][4] = 179.9, -179.9
            robot.state()
            assert writes[-1] == {"left": 179.9, "right": -179.9}
            assert not robot.roll_active and not robot.roll_holding
            count = len(writes)
            robot.state()
            assert len(writes) == count
        finally:
            robot.close()
            server.shutdown()
            thread.join(timeout=2)


def test_sim_roll_uses_feedback_and_hold_preserves_measured_tools():
    from telesurgery_robots.mira.poses import roll_target

    robot = SimRobot()
    robot.feedback = {"joints_deg": {"left": [0, 0, 0, 0, 179.8], "right": [0, 0, 0, 0, -179.8]}}
    command = {
        "method": "set_mira_cartesian_delta",
        "params": {"left": [0, 0, 0, 0, 1], "right": [0, 0, 0, 0, -1]},
    }
    for _ in range(2):
        robot.apply(command)
        assert robot.pose["left"][4] == 180 and robot.pose["right"][4] == -180
    robot.apply({"method": "hold"})
    assert robot.pose["left"][4] == 179.8 and robot.pose["right"][4] == -179.8
    assert roll_target(185, -1) == 184  # Inward jog, without snapping to a limit.
    with pytest.raises(ValueError, match="outside"):
        roll_target(185, 1)
