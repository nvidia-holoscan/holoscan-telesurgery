# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Node startup opens devices once; manual stops and admission loss take precedence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telesurgery.nodes.service import NodeService


@pytest.fixture
def node(monkeypatch, tmp_path):
    service = NodeService(tmp_path, AsyncMock())
    service.robots = SimpleNamespace(sync=Mock(), report=lambda: {}, devices={})
    service.room = SimpleNamespace(changing=False, error="", task=None, status=lambda: {})
    service.room.close = AsyncMock()
    robot = {"id": "arm", "kind": "franka", "profile": "franka", "connection_enabled": False}
    cameras = [{"id": "camera", "name": "Camera", "status": "stopped", "codec": "h264"}]

    async def refresh():
        service.local.robots = {"arm": dict(robot)}
        service.local.cameras = {item["id"]: dict(item) for item in cameras}

    service.local.refresh = refresh
    service.local.inventory = lambda: {"cameras": [dict(c) for c in service.local.cameras.values()]}
    service.local.start_camera = AsyncMock()
    service.local.stop_camera = AsyncMock()
    monkeypatch.setattr(
        "telesurgery.nodes.service.require_sdk", lambda: SimpleNamespace(__version__="5")
    )
    monkeypatch.setattr("telesurgery.nodes.service.simulation_support", lambda: {})
    yield service, cameras
    service.local.context.term()
    service.local.temp.cleanup()


@pytest.mark.asyncio
async def test_start_connects_robot_and_streams_once_and_respects_manual_stop(node):
    service, _ = node
    await service.call("inventory")
    service.local.start_camera.assert_not_called()  # No start before node admission.
    await service.start()
    await asyncio.gather(*service.camera_starts.values())
    service.local.start_camera.assert_awaited_once_with("camera")
    assert service.local.robots["arm"]["connection_enabled"]
    await service.call("camera.stop", {"id": "camera"})
    await service.call("robot.disconnect", {"id": "arm"})
    await service.call("inventory")
    service.local.start_camera.assert_awaited_once()
    assert not service.local.robots["arm"]["connection_enabled"]
    await service.close()


@pytest.mark.asyncio
async def test_delayed_simulation_discovery_and_start_failure_are_visible_without_retry(node):
    service, cameras = node
    service.room.status = lambda: {"simulation": {"status": "loading"}}
    await service.start()
    service.local.start_camera.assert_not_called()
    service.room.status = lambda: {"simulation": {"status": "ready"}}
    service.local.start_camera.side_effect = RuntimeError("Camera busy")
    await service.call("inventory")
    await asyncio.gather(*service.camera_starts.values())
    inventory = await service.call("inventory")
    assert inventory["cameras"][0]["error"] == "Camera busy"
    service.local.start_camera.assert_awaited_once()
    cameras.append({"id": "second", "name": "Second", "status": "stopped"})
    await service.call("inventory")
    await asyncio.gather(*service.camera_starts.values())
    assert service.local.start_camera.await_count == 2
    await service.close()


@pytest.mark.asyncio
async def test_stop_during_automatic_process_creation_cleans_up_before_returning(node):
    service, _ = node
    entered, finish = asyncio.Event(), asyncio.Event()

    async def starting(key):
        entered.set()
        await finish.wait()

    service.local.start_camera.side_effect = starting
    await service.start()
    await entered.wait()
    stopping = asyncio.create_task(service.call("camera.stop", {"id": "camera"}))
    await asyncio.sleep(0)
    assert not stopping.done()
    finish.set()
    await stopping
    service.local.stop_camera.assert_awaited_with("camera")
    assert not service.camera_starts
    await service.call("inventory")
    service.local.start_camera.assert_awaited_once()
    await service.close()


@pytest.mark.asyncio
async def test_link_reconnect_resumes_only_interrupted_streams(node):
    service, cameras = node
    cameras.append({"id": "manual", "name": "Manual", "status": "stopped"})

    async def start(key):
        service.local.workers[key] = {}

    async def stop(key):
        service.local.workers.pop(key, None)

    service.local.start_camera.side_effect = start
    service.local.stop_camera.side_effect = stop
    await service.start()
    await asyncio.gather(*service.camera_starts.values())
    await service.call("camera.stop", {"id": "manual"})
    await service.disconnect()
    assert not service.local.workers
    service.local.start_camera.reset_mock()
    await service.call("inventory")
    await asyncio.gather(*service.camera_starts.values())
    service.local.start_camera.assert_awaited_once_with("camera")
    await service.disconnect()
    await service.close()


@pytest.mark.asyncio
async def test_explicit_startup_opt_out_still_allows_manual_start(node):
    service, cameras = node
    cameras[0]["auto_start"] = False
    refresh = service.local.refresh

    async def opted_out():
        await refresh()
        service.local.robots["arm"]["auto_connect"] = False

    service.local.refresh = opted_out
    controller = SimpleNamespace(
        owned=False,
        start=AsyncMock(),
        stop=AsyncMock(),
        status=AsyncMock(return_value={"status": "stopped"}),
    )

    async def started():
        controller.owned = True
        controller.status.return_value = {"status": "running"}

    controller.start.side_effect = started
    service.controllers["arm"] = controller
    service.controller = lambda key: controller
    await service.start()
    service.local.start_camera.assert_not_called()
    controller.start.assert_not_called()
    assert not service.local.robots["arm"]["connection_enabled"]
    await service.call("camera.start", {"id": "camera"})
    await service.call("robot.connect", {"id": "arm"})
    service.local.start_camera.assert_awaited_once_with("camera", None)
    assert service.local.robots["arm"]["connection_enabled"]
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_managed_controller_starts_after_admission_and_failures_require_manual_retry(
    node, failure
):
    service, _ = node
    controller = SimpleNamespace(
        owned=False,
        start=AsyncMock(side_effect=RuntimeError("Missing controller image") if failure else None),
        stop=AsyncMock(),
        status=AsyncMock(return_value={"status": "stopped", "error": ""}),
    )
    service.controllers["arm"] = controller
    service.controller = lambda key: controller
    connections = []
    service.robots.sync.side_effect = lambda: connections.append(
        service.local.robots["arm"].get("connection_enabled", False)
    )

    async def started():
        controller.owned = True
        controller.status.return_value = {"status": "running", "error": ""}

    if not failure:
        controller.start.side_effect = started
    await service.call("inventory")
    controller.start.assert_not_called()
    await service.start()
    controller.start.assert_awaited_once()
    inventory = await service.call("inventory")
    controller.start.assert_awaited_once()
    if failure:
        assert not any(connections)  # Never attach to a pre-existing vendor API.
        assert inventory["robots"][0]["controller"]["error"] == "Missing controller image"
        controller.start.side_effect = started
        await service.call("robot.start", {"id": "arm"})
        assert controller.start.await_count == 2
        assert not service.controller_errors
    assert service.local.robots["arm"]["connection_enabled"]
    await service.close()


@pytest.mark.asyncio
async def test_cancel_during_controller_creation_finishes_before_shutdown(node):
    service, _ = node
    entered, finish = asyncio.Event(), asyncio.Event()

    async def start():
        entered.set()
        await finish.wait()

    controller = SimpleNamespace(
        owned=False,
        start=AsyncMock(side_effect=start),
        stop=AsyncMock(),
        status=AsyncMock(return_value={"status": "stopped"}),
    )
    service.controllers["arm"] = controller
    service.controller = lambda key: controller
    startup = asyncio.create_task(service.start())
    await entered.wait()
    startup.cancel()
    await asyncio.sleep(0)
    assert not startup.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await startup
    await service.close()
    controller.stop.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fails", [False, True])
async def test_inventory_removal_closes_adapter_before_ending_vendor_lease(node, adapter_fails):
    service, _ = node
    events = []

    async def refresh():
        service.local.robots = {}

    def sync():
        events.append("adapter")
        if adapter_fails:
            raise RuntimeError("Adapter shutdown unconfirmed")

    async def stop():
        events.append("vendor")

    service.local.refresh = refresh
    service.robots.sync.side_effect = sync
    controller = SimpleNamespace(stop=AsyncMock(side_effect=stop))
    service.controllers["removed"] = controller
    service.controller_errors["removed"] = "Old startup error"
    if adapter_fails:
        with pytest.raises(RuntimeError, match="Adapter shutdown unconfirmed"):
            await service.call("inventory")
    else:
        await service.call("inventory")
    assert events == ["adapter", "vendor"]
    assert not service.controllers
    assert not service.controller_errors
    await service.close()
    controller.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_stops_cached_controllers_after_inventory_disappears(node):
    service, _ = node
    first = SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("Docker unavailable")))
    second = SimpleNamespace(stop=AsyncMock())
    service.controllers.update(first=first, second=second)
    service.local.robots = {}
    # Shutdown must use owned instances, not reconstruct controllers from inventory.
    service.controller = Mock(side_effect=AssertionError("Unexpected controller creation"))
    with pytest.raises(RuntimeError, match="Docker unavailable"):
        await service.close()
    first.stop.assert_awaited_once()
    second.stop.assert_awaited_once()
    assert not service.controllers
    service.controller.assert_not_called()
