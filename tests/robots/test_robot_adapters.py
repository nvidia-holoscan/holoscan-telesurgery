# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A new robot kind uses the same graph, admission, feedback and watchdog."""

import asyncio
import math
import time

import pytest
from telesurgery_robots.adapters.registry import adapter_type
from telesurgery_runtime.application.robots import Controller, Robots


class Gantry:
    simulation = True
    groups = {"axis": 2}
    max_step_deg = 0.4

    def __init__(self, spec):
        self.position = [0, 0]
        self.fail = spec.get("fail", False)
        self.closed = self.holds = 0

    def read(self):
        if self.fail:
            time.sleep(0.3)
            raise ConnectionError("controller unavailable")
        return {"joints_deg": {"axis": list(self.position)}}

    def jog(self, command):
        self.position = [a + b for a, b in zip(self.position, command["axis"], strict=True)]
        return self.read()

    def hold(self):
        self.holds += 1
        return self.read()

    def close(self):
        self.closed += 1


def test_installed_adapters_and_unknown_kind():
    for kind in ("mira", "mira-sim", "franka-sim", "franka"):
        assert adapter_type(kind)
    with pytest.raises(ValueError, match="No controller adapter"):
        adapter_type("uninstalled-robot")


def test_franka_adjustable_steps_and_jogs_enforce_the_controller_limit():
    from types import SimpleNamespace

    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.franka.adapter import Franka

    moves = []
    adapter = Franka.__new__(Franka)
    adapter.reader = SimpleNamespace(jog=lambda delta, **kwargs: moves.append((delta, kwargs)))
    adapter.read = lambda: {}
    assert controls(adapter, {"motion_enabled": True})["max_step_deg"] == 5
    for size in (0.05, -0.2, 0.5, -1):
        adapter.step({"joints": [size] + [0] * 6})
    assert len(moves) == 4 and all(
        options == {"step": True, "speed": math.radians(10)} for _, options in moves
    )
    for size in (5.01, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            adapter.step({"joints": [size] + [0] * 6})
    assert len(moves) == 4
    adapter.jog({"joints": [0.5] + [0] * 6})
    assert moves[-1][1] == {"step": False, "speed": math.radians(10)}
    controller = Controller(adapter, lambda: {"motion_enabled": True}, lambda: 0)
    controller.prepare("owner")
    with pytest.raises(ValueError):
        controller.move("owner", 1, {"joints": [5.01] + [0] * 6}, time.time())
    assert controller.report()["status"] == "online"
    controller.move("owner", 1, {"joints": [0.5] + [0] * 6}, time.time(), mode="step")
    assert moves[-1][1] == {"step": True, "speed": math.radians(10)}


def test_generic_validation_expiry_and_failed_hold():
    adapter = Gantry({})
    robot = Controller(adapter, lambda: {}, lambda: 0)
    robot.prepare("owner")
    now = time.time()
    for command in ({"axis": [float("nan"), 0]}, {"left": [0, 0]}, {"axis": [0.5, 0]}):
        with pytest.raises(ValueError):
            robot.move("owner", 1, command, now)
    assert adapter.position == [0, 0]
    with pytest.raises(ValueError, match="expired"):
        robot.move("owner", 1, {"axis": [0.1, 0]}, now - 1)
    robot.move("owner", 1, {"axis": [0.1, 0]}, now)
    with pytest.raises(ValueError, match="Stale"):
        robot.move("owner", 1, {"axis": [0.1, 0]}, now)
    robot.expires = 0
    adapter.fail = True
    robot.tick()
    assert robot.token is None and robot.active
    assert robot.report()["stale"]
    with pytest.raises(PermissionError, match="awaiting hold"):
        robot.prepare("next")
    adapter.fail = False
    robot.next_poll = 0
    robot.tick()
    assert not robot.active and not robot.report()["stale"]
    robot.prepare("next")
    robot.close()
    assert adapter.closed == 1


def test_closed_controller_does_not_reopen_feedback_connection():
    class Reconnecting(Gantry):
        def read(self):
            self.connected = True
            return super().read()

        def close(self):
            self.connected = False
            super().close()

    adapter = Reconnecting({})
    controller = Controller(adapter, lambda: {}, lambda: 0)
    controller.state()
    controller.close()
    controller.observed = 0
    controller.tick()  # An idle callback can run before the graph finishes stopping.
    assert not adapter.connected
    with pytest.raises(RuntimeError, match="disconnected"):
        controller.prepare("late-owner")


def test_franka_disconnect_explicitly_closes_native_connection():
    from types import SimpleNamespace

    from telesurgery_robots.franka.adapter import Franka

    native = SimpleNamespace(closed=False)
    native.close = lambda: setattr(native, "closed", True)
    adapter = Franka.__new__(Franka)
    adapter.reader = native
    adapter.close()
    assert native.closed and adapter.reader is None
    adapter.close()  # A repeated Disconnect succeeds without reconnecting.


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_independent_graphs_publish_idle_feedback_and_close_removed_robot(monkeypatch):
    pytest.importorskip("holoscan")
    monkeypatch.setattr("telesurgery_runtime.application.robots.adapter_type", lambda _: Gantry)
    specs = {"slow": {"kind": "custom", "fail": True}, "ready": {"kind": "custom"}}
    robots = Robots(lambda: specs)
    await asyncio.to_thread(robots.sync)
    try:
        async with asyncio.timeout(5):
            while robots.report()["ready"]["status"] != "online":
                await asyncio.sleep(0.02)
        before = robots.report()["ready"]["state"]["sequence"]
        device = robots.devices["ready"].adapter
        device.position[0] = 12
        async with asyncio.timeout(2):
            while robots.report()["ready"]["state"]["sequence"] <= before:
                await asyncio.sleep(0.02)
        assert robots.report()["ready"]["state"]["joints_deg"]["axis"][0] == 12
        await asyncio.wrap_future(robots.submit("prepare", "ready", token="owner"))
        # The local graph releases even when nobody sends a renew/expire RPC.
        robots.devices["ready"].expires = 0
        async with asyncio.timeout(2):
            while robots.devices["ready"].active:
                await asyncio.sleep(0.02)
        assert device.holds == 1
        del specs["ready"]
        await asyncio.to_thread(robots.sync)
        assert device.closed == 1 and "ready" not in robots.report()
    finally:
        await asyncio.to_thread(robots.close)


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_node_robot_feedback_reaches_view_only_surgeon(tmp_path, monkeypatch, enrolled_node):
    pytest.importorskip("holoscan")
    from telesurgery.server.application import Application

    class StepGantry(Gantry):
        home_deg = {"axis": [0, 0]}
        speed_limits = {"min": 0.2, "max": 10, "default": 2}

        def home(self, *, speed_deg_s):
            self.speed = speed_deg_s
            self.position = [0, 0]
            return self.read()

        def step(self, command, *, speed_deg_s):
            self.speed = speed_deg_s
            self.stepped = True
            return self.jog(command)

    monkeypatch.setattr("telesurgery_runtime.application.robots.adapter_type", lambda _: StepGantry)
    monkeypatch.setattr(
        "telesurgery.nodes.local.discover",
        lambda *_: ([], [{"id": "gantry", "name": "Gantry", "kind": "custom"}]),
    )
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    try:
        await patient.start()
        await surgeon.start()
        node, node_id = await enrolled_node(patient, tmp_path / "node")
        identity = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", "Observer", False)
        await patient.action("access.approve", {"id": identity["id"], "robot": False})
        node.node.robots.devices["gantry"].adapter.position[1] = 23
        key = f"{node_id}:gantry"
        async with asyncio.timeout(10):
            while True:
                robot = next(
                    (r for r in surgeon.remote_status.get("robots", []) if r["id"] == key), None
                )
                if robot and robot.get("state", {}).get("joints_deg", {}).get("axis") == [0, 23]:
                    break
                await asyncio.sleep(0.05)
        assert robot["controls"]["groups"] == {"axis": 2}
        assert not robot["stale"]
        with pytest.raises(RuntimeError, match="robot|Robot"):
            await surgeon.action("robot.move", {"id": key, "command": {"axis": [0.1, 0]}})
        await surgeon.action("disconnect", {})
        identity = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", "Operator", True)
        await patient.action("access.approve", {"id": identity["id"], "robot": True})
        async with asyncio.timeout(5):
            while not surgeon.remote_status.get("robot"):
                await asyncio.sleep(0.05)
        result = await surgeon.action(
            "robot.move",
            {"id": key, "command": {"axis": [0.2, 0]}, "mode": "step", "speed_deg_s": 3.5},
        )
        assert result["joints_deg"]["axis"] == [0.2, 23]
        assert node.node.robots.devices["gantry"].adapter.stepped
        assert node.node.robots.devices["gantry"].adapter.speed == 3.5
        result = await surgeon.action("robot.move", {"id": key, "command": {}, "mode": "home"})
        assert result["joints_deg"]["axis"] == [0, 0]
        assert node.node.robots.devices["gantry"].adapter.speed == 2
        await surgeon.action("robot.release", {"id": key})
        assert key not in surgeon.tokens
        patient.faults[key] = "Previous Home timed out"
        patient.owners[key].ready = False
        await patient._recover_holds()
        assert key not in patient.faults and patient.owners[key].ready
        assert patient.owners[key].owner is None
        assert not node.node.robots.devices["gantry"].active
        # A rejected move must retain the credential needed to stop/release it;
        # otherwise the original error becomes a misleading ownership failure.
        with pytest.raises(RuntimeError):
            await surgeon.action("robot.move", {"id": key, "command": {"axis": [1, 0]}})
        assert key in surgeon.tokens
        await surgeon.action("robot.release", {"id": key})
        assert patient.owners[key].owner is None
        assert not node.node.robots.devices["gantry"].active
        await surgeon.action(
            "robot.move", {"id": key, "command": {"axis": [0.1, 0]}, "mode": "step"}
        )
        await patient.action("robot.revoke", {"id": key})
        with pytest.raises(RuntimeError, match="expired|belongs"):
            await surgeon.action(
                "robot.move", {"id": key, "command": {"axis": [0.1, 0]}, "mode": "step"}
            )
        assert key not in surgeon.tokens
        # A fresh user input can acquire a new lease; the failed command was not replayed.
        result = await surgeon.action(
            "robot.move", {"id": key, "command": {"axis": [0.1, 0]}, "mode": "step"}
        )
        assert result["joints_deg"]["axis"] == [0.2, 0]
        await surgeon.action("robot.release", {"id": key})
    finally:
        await surgeon.close()
        await patient.close()


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_patient_connection_releases_hardware_and_keeps_device_listed(tmp_path, monkeypatch):
    from telesurgery.nodes.service import NodeService
    from telesurgery_core.configuration import load, save

    class Physical(Gantry):
        simulation = False
        manages_connection = True

        def read(self):
            self.connected = True
            return super().read()

        def close(self):
            self.connected = False
            super().close()

    path = tmp_path / "devices.yaml"
    save(
        path, {"robots": [{"id": "arm", "name": "Arm", "kind": "physical", "motion_enabled": True}]}
    )
    monkeypatch.setattr("telesurgery_runtime.application.robots.adapter_type", lambda _: Physical)
    monkeypatch.setattr("telesurgery.nodes.service.adapter_type", lambda _: Physical)
    monkeypatch.setattr("telesurgery.nodes.local.discover", lambda *_: ([], load(path)["robots"]))
    node = NodeService(tmp_path, lambda *_: None)
    try:
        initial = await node.call("inventory")
        assert initial["robots"][0]["status"] == "disconnected"
        assert not node.robots.devices
        await node.call("robot.connect", {"id": "arm"})
        adapter = node.robots.devices["arm"].adapter
        await node.call("robot.prepare", {"key": "arm", "token": "owner"})
        graph = node.robots.graphs["arm"]
        original_close = graph.close

        def delayed_stop():
            time.sleep(0.3)  # Feedback may tick after adapter.close(), before graph shutdown.
            original_close()

        graph.close = delayed_stop
        disconnected = await node.call("robot.disconnect", {"id": "arm"})
        assert adapter.holds == adapter.closed == 1
        assert not adapter.connected
        assert disconnected["robots"][0]["status"] == "disconnected"
        assert not load(path)["robots"][0]["connection_enabled"]
        await node.call("inventory")
        assert not node.robots.devices
        await node.call("robot.disconnect", {"id": "arm"})
        assert not adapter.connected
        with pytest.raises(RuntimeError):
            await node.call(
                "robot.move",
                {
                    "key": "arm",
                    "token": "owner",
                    "sequence": 1,
                    "command": {"axis": [0.1, 0]},
                    "sent_at": time.time(),
                },
            )
        await node.call("robot.connect", {"id": "arm"})
        assert node.robots.devices["arm"].adapter is not adapter
        assert node.robots.report()["arm"]["controls"]["inputs"] == [
            "keyboard",
            "gamepad",
        ]
        current = node.robots.devices["arm"].adapter
        close = current.close
        failed = False

        def fails_once():
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("connection still open")
            close()

        current.close = fails_once
        with pytest.raises(RuntimeError, match="still open"):
            await node.call("robot.disconnect", {"id": "arm"})
        assert "arm" in node.robots.devices  # Keep the handle so cleanup can be retried.
        assert node.robots.report()["arm"]["status"] == "offline"
        disconnected = await node.call("inventory")
        assert disconnected["robots"][0]["status"] == "disconnected"
        assert not current.connected and not node.robots.devices
    finally:
        await node.close()


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_discovery_and_disconnect_cannot_close_the_same_graph_concurrently(monkeypatch):
    class SlowClose(Gantry):
        def close(self):
            time.sleep(0.1)
            super().close()

    monkeypatch.setattr("telesurgery_runtime.application.robots.adapter_type", lambda _: SlowClose)
    specs = {"arm": {"kind": "custom"}}
    robots = Robots(lambda: specs)
    await asyncio.to_thread(robots.sync)
    adapter = robots.devices["arm"].adapter
    specs.clear()
    await asyncio.gather(asyncio.to_thread(robots.sync), asyncio.to_thread(robots.close))
    assert not robots.devices and adapter.closed == 1


def test_discrete_step_uses_adapter_completion_without_repeating_input():
    class Servo(Gantry):
        def step(self, command):
            self.target = command
            return {"control_active": True}

    adapter = Servo({})
    robot = Controller(adapter, lambda: {}, lambda: 0)
    robot.prepare("owner")
    command = {"axis": [0.2, 0]}
    result = robot.move("owner", 1, command, time.time(), mode="step")
    assert result["control_active"]
    assert adapter.target == command and adapter.position == [0, 0]
    # The independent node lease still cancels the finite motion on disconnect.
    robot.expires = 0
    robot.tick()
    assert adapter.holds == 1
    with pytest.raises(ValueError, match="motion mode"):
        robot.move("owner", 2, command, time.time(), mode="unknown")


def test_mira_simulation_home_restores_both_arms_and_preserves_tools():
    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.adapters.simulation import MiraSimulation
    from telesurgery_robots.mira.adapter import MiraAdapter
    from telesurgery_robots.mira.poses import MIRA_HOME
    from telesurgery_robots.simulation.state import SimRobot

    sim = SimRobot("mira")
    adapter = MiraSimulation({"uri": "unused"})
    adapter.request = lambda method, params=None: sim.apply({"method": method, "params": params})
    capabilities = controls(adapter, {})
    assert capabilities["default_step_deg"] == 1
    assert capabilities["home_deg"] == {"left": MIRA_HOME, "right": MIRA_HOME}
    for arm in sim.pose:
        sim.pose[arm][4:] = [12, 34]
    controller = Controller(adapter, lambda: {}, lambda: 0)
    with pytest.raises(PermissionError):
        controller.move("owner", 1, {}, time.time(), mode="home")
    controller.prepare("owner")
    moved = controller.move(
        "owner", 1, {"left": [1, 1, 1, 1, 0], "right": [1, 1, 1, 1, 0]}, time.time()
    )
    assert all(pose[:4] != list(MIRA_HOME) for pose in moved["targets_deg"].values())
    restored = controller.move("owner", 2, {}, time.time(), mode="home")
    assert restored["targets_deg"] == {arm: [*MIRA_HOME, 12, 34] for arm in ("left", "right")}
    with pytest.raises(ValueError, match="configured pose"):
        sim.apply({"method": "set_home", "params": {"left": [0] * 4}})
    # Physical controls require patient motion permission.
    physical = MiraAdapter({"uri": "unused"})
    assert "home_deg" not in controls(physical, {})
    assert controls(physical, {"motion_enabled": True})["default_step_deg"] == 1


def test_home_uses_shared_pose_and_preserves_admission_and_stop():
    from types import SimpleNamespace

    from telesurgery_robots.adapters.base import controls
    from telesurgery_robots.adapters.simulation import FrankaSimulation
    from telesurgery_robots.franka.adapter import Franka
    from telesurgery_robots.franka.poses import FRANKA_HOME
    from telesurgery_robots.simulation.state import SimRobot
    from telesurgery_sim.environments.presets import PRESETS

    assert list(FRANKA_HOME) == PRESETS["franka"]["joints"]
    sim = SimRobot("franka")
    adapter = FrankaSimulation({"uri": "unused"})
    adapter.request = lambda method, params=None: sim.apply({"method": method, "params": params})
    assert adapter.home()["targets_deg"]["joints"] == list(FRANKA_HOME)
    adapter.hold()
    with pytest.raises(ValueError, match="configured pose"):
        sim.apply({"method": "set_home", "params": {"joints": [0] * 7}})

    calls = []
    physical = Franka.__new__(Franka)
    physical.reader = SimpleNamespace(home=lambda goal, **kwargs: calls.append((goal, kwargs)))
    physical.read = lambda: {"control_active": bool(calls), "home_active": bool(calls)}
    physical.hold = lambda: calls.clear() or {"control_active": False}
    enabled = {"motion_enabled": True}
    controller = Controller(physical, lambda: enabled, lambda: 0)
    assert "home_deg" not in controls(physical, {})
    assert controls(physical, enabled)["home_deg"] == {"joints": FRANKA_HOME}
    with pytest.raises(PermissionError):
        controller.move("owner", 1, {}, time.time(), mode="home")
    controller.prepare("owner")
    with pytest.raises(ValueError, match="expired"):
        controller.move("owner", 1, {}, time.time() - 1, mode="home")
    with pytest.raises(ValueError, match="configured pose"):
        controller.move("owner", 1, {"joints": [0] * 7}, time.time(), mode="home")
    assert not calls
    result = controller.move("owner", 1, {}, time.time(), mode="home")
    assert result["home_active"]
    import math

    assert calls[0] == ([math.radians(v) for v in FRANKA_HOME], {"speed": math.radians(10)})
    with pytest.raises(ValueError, match="Stale"):
        controller.move("owner", 1, {}, time.time(), mode="home")
    controller.expires = 0
    controller.tick()
    assert not calls and not controller.active
    enabled["motion_enabled"] = False
    with pytest.raises(PermissionError):
        controller.prepare("owner")

    unsupported = Controller(Gantry({}), lambda: {}, lambda: 0)
    unsupported.prepare("owner")
    with pytest.raises(ValueError, match="not supported"):
        unsupported.move("owner", 1, {}, time.time(), mode="home")


@pytest.mark.asyncio
async def test_simulation_connection_remains_disconnected_after_discovery(tmp_path, monkeypatch):
    import json

    from telesurgery.nodes.service import NodeService
    from telesurgery_core.configuration import load

    monkeypatch.setattr("telesurgery_runtime.application.robots.adapter_type", lambda _: Gantry)
    monkeypatch.setattr("telesurgery.nodes.service.adapter_type", lambda _: Gantry)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"cameras": [], "robots": [{"id": "arm", "name": "Arm", "kind": "gantry"}]})
    )
    node = NodeService(tmp_path, lambda *_: None)
    node.local.simulation = manifest
    try:
        await node.call("inventory")
        adapter = node.robots.devices["arm"].adapter
        await node.call("robot.prepare", {"key": "arm", "token": "owner"})
        await node.call("robot.disconnect", {"id": "arm"})
        assert adapter.holds == adapter.closed == 1
        assert load(tmp_path / "connections.yaml") == {"arm": False}
        assert not (await node.call("inventory"))["robots"][0]["connection_enabled"]
        assert not node.robots.devices
        await node.call("robot.connect", {"id": "arm"})
        assert node.robots.devices["arm"].adapter is not adapter
    finally:
        await node.close()


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_node_clock_excludes_slow_discovery(tmp_path, monkeypatch, enrolled_node):
    from telesurgery.nodes.service import NodeService
    from telesurgery.server.application import Application

    node_dir = tmp_path / "node"
    monkeypatch.setattr("telesurgery_runtime.application.robots.adapter_type", lambda _: Gantry)
    monkeypatch.setattr("telesurgery.nodes.service.adapter_type", lambda _: Gantry)
    monkeypatch.setattr(
        "telesurgery.nodes.local.discover",
        lambda *_: ([], [{"id": "arm", "name": "Arm", "kind": "gantry"}]),
    )
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)
    original = NodeService.call
    instances, clocks = [], []

    async def slow_discovery(self, action, params=None):
        if self.local.directory == node_dir and action == "inventory":
            if self not in instances:
                instances.append(self)
            clocks.append(self.robots.clock_offset)
            await asyncio.sleep(0.7)
        return await original(self, action, params)

    monkeypatch.setattr(NodeService, "call", slow_discovery)
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    task = None
    try:
        await patient.start()
        node, node_id = await enrolled_node(patient, node_dir, name="slow")
        async with asyncio.timeout(10):
            while len(clocks) < 3:
                await asyncio.sleep(0.05)
        # The third discovery starts after registration. Its 700 ms duration must
        # not create a 350 ms clock offset and expire otherwise fresh commands.
        assert abs(clocks[2]) < 0.05
        await surgeon.start()
        grant = await surgeon.connect(f"127.0.0.1:{patient.endpoint_port}", "Operator", True)
        await patient.action("access.approve", {"id": grant["id"], "robot": True})
        async with asyncio.timeout(10):
            while surgeon.remote_status.get("status") != "approved":
                await asyncio.sleep(0.05)
        result = await surgeon.action(
            "robot.move",
            {
                "id": f"{node_id}:arm",
                "command": {"axis": [0.2, 0]},
                "mode": "step",
            },
        )
        assert result["joints_deg"]["axis"] == [0.2, 0]
        await surgeon.action("robot.release", {"id": f"{node_id}:arm"})
        # A later inventory exchange refreshes the estimate, without discovery cost.
        instances[0].robots.clock_offset = 1
        async with asyncio.timeout(10):
            while abs(instances[0].robots.clock_offset) > 0.05:
                await asyncio.sleep(0.05)
    finally:
        await surgeon.close()
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await patient.close()


@pytest.mark.parametrize("speed", [0.2, 2.0, 10.0, 20.0])
def test_franka_speed_reaches_native_controller_and_rejects_bad_values(speed):
    from types import SimpleNamespace

    from telesurgery_robots.franka.adapter import Franka

    moves = []
    adapter = Franka.__new__(Franka)
    adapter.reader = SimpleNamespace(jog=lambda delta, **kwargs: moves.append(kwargs))
    adapter.read = lambda: {}
    controller = Controller(adapter, lambda: {"motion_enabled": True}, lambda: 0)
    controller.prepare("owner")
    command = {"joints": [0.2] + [0] * 6}
    for invalid in (0, 20.1, True, "2", float("nan"), float("inf")):
        with pytest.raises(ValueError, match="Speed"):
            controller.move("owner", 1, command, time.time(), speed_deg_s=invalid)
    assert not moves
    controller.move("owner", 1, command, time.time(), mode="step", speed_deg_s=speed)
    assert moves == [{"step": True, "speed": math.radians(speed)}]


@pytest.mark.parametrize("speed", [0.2, 2.0, 10.0, 20.0])
def test_simulated_franka_ramps_stops_and_homes(monkeypatch, speed):
    from telesurgery_robots.adapters.simulation import FrankaSimulation
    from telesurgery_robots.franka.poses import FRANKA_HOME
    from telesurgery_robots.simulation.state import SimRobot

    clock = [100.0]
    monkeypatch.setattr("telesurgery_robots.simulation.state.time.monotonic", lambda: clock[0])
    sim = SimRobot("franka")
    adapter = FrankaSimulation({"uri": "unused"})
    adapter.request = lambda method, params=None: sim.apply({"method": method, "params": params})
    command = {"joints": [5] + [0] * 6}
    adapter.step(command, speed_deg_s=speed)
    assert sim.pose["joints"] == list(FRANKA_HOME)  # No jump on acceptance.
    trajectory = sim.trajectory
    adapter.step({"joints": [-1] + [0] * 6}, speed_deg_s=speed)
    assert sim.trajectory is trajectory
    assert trajectory.input.target_position[0] == FRANKA_HOME[0] + 4
    last = sim.pose["joints"][0]
    for _ in range(10):
        clock[0] += 0.01
        state = adapter.read()
        current = state["targets_deg"]["joints"][0]
        assert 0 <= current - last <= speed * 0.01 + 1e-9
        last = current
    assert last > FRANKA_HOME[0]
    adapter.hold()
    for _ in range(300):
        clock[0] += 0.01
        state = adapter.read()
        if not state["control_active"]:
            break
    assert not state["control_active"]
    stopped = state["targets_deg"]["joints"][0]
    assert last <= stopped < FRANKA_HOME[0] + 5
    clock[0] += 1
    assert adapter.read()["targets_deg"]["joints"][0] == stopped
    state = adapter.home(speed_deg_s=speed)
    assert state["home_active"]
    for _ in range(4000):
        clock[0] += 0.01
        state = adapter.read()
        if not state["control_active"]:
            break
    assert state["targets_deg"]["joints"] == pytest.approx(FRANKA_HOME, abs=0.01)
    assert not state["home_active"]
    adapter.jog(command, speed_deg_s=speed)
    clock[0] += 0.3
    for _ in range(300):
        state = adapter.read()
        if not state["control_active"]:
            break
        clock[0] += 0.01
    assert not state["control_active"]  # Expiry triggers a local braking trajectory.


@pytest.mark.parametrize("joint", range(7))
@pytest.mark.parametrize("ending", ["release", "expired"])
def test_held_franka_key_promotes_active_step_and_stops(monkeypatch, joint, ending):
    from telesurgery_robots.simulation.state import SimRobot

    clock = [100.0]
    monkeypatch.setattr("telesurgery_robots.simulation.state.time.monotonic", lambda: clock[0])
    sim = SimRobot("franka")
    initial = sim.pose["joints"][joint]
    delta = [0.0] * 7
    delta[joint] = -1

    def move(step=False):
        return sim.apply({"method": "set_joint_delta", "params": {"joints": delta, "step": step}})

    move(step=True)
    for _ in range(45):
        clock[0] += 0.01
        sim.advance()
    assert sim.mode == "step"  # Held input arrives before initial step completion.
    trajectory = sim.trajectory
    for _ in range(80):
        move()
        assert sim.trajectory is trajectory  # Carry velocity/acceleration through promotion.
        clock[0] += 0.05
        sim.advance()
    assert sim.pose["joints"][joint] < initial - 2
    if ending == "release":
        sim.apply({"method": "hold"})
    else:
        clock[0] += 0.21
        sim.advance()
    with pytest.raises(ValueError, match="stopping"):
        move()  # Input cannot override braking.
    for _ in range(300):
        clock[0] += 0.01
        sim.advance()
    assert sim.trajectory is None
    stopped = list(sim.pose["joints"])
    clock[0] += 1
    sim.advance()
    assert sim.pose["joints"] == stopped
    sim.apply({"method": "set_home"})
    with pytest.raises(ValueError, match="moving home"):
        move()  # Home cannot be promoted into manual control.
