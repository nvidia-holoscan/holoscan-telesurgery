# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Device discovery and control on a local or remote device node."""

import asyncio
import logging

from telesurgery.nodes.local import LocalNode
from telesurgery_core.configuration import load, save
from telesurgery_robots.adapters.registry import adapter_type
from telesurgery_runtime.application.robots import Robots
from telesurgery_runtime.backends.sdk import require_sdk
from telesurgery_sim.runtime.capabilities import simulation_support


class NodeService:
    def __init__(self, directory, publish):
        from telesurgery.nodes.simulation import NodeSimulation

        self.local = LocalNode(directory, publish)
        self.robots = Robots(lambda: self.local.robots)
        self.controller_lock = asyncio.Lock()
        self.room = NodeSimulation(self)
        self.started = False
        self.connection_choices = {}
        self.started_cameras = set()
        self.camera_starts = {}
        self.start_errors = {}
        self.controller_errors = {}

    async def start(self, environment=None, sim_gui=False):
        self.started = True
        if environment:
            self.room.start(environment, sim_gui)
        await self.call("inventory")
        for key, spec in self.local.robots.items():
            if not spec.get("connection_enabled", True):
                continue
            try:
                controller = self.controller(key)
                if controller is None:
                    continue
                operation = asyncio.create_task(controller.start())
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    # Complete process creation so close() can stop the owned
                    # controller, including cancellation while Docker launches.
                    await asyncio.gather(operation, return_exceptions=True)
                    raise
            except Exception as exc:
                self.controller_errors[key] = str(exc) or type(exc).__name__
                logging.warning(
                    "Controller %s could not start: %s", key, self.controller_errors[key]
                )

    async def call(self, action, params=None):
        params = params or {}
        room = self.room.status() if self.room else {}
        if action == "camera.start" and (room.get("simulation") or {}).get("status") not in (
            None,
            "ready",
        ):
            raise RuntimeError("Simulation is not ready; open the node logs")
        if action == "inventory":
            async with self.controller_lock:
                if not self.room or not (self.room.changing or self.room.error):
                    await self.local.refresh()
                if self.started:
                    # Connection is a session choice. A new node process starts
                    # connected; an explicit Disconnect remains off until restart.
                    for key, spec in self.local.robots.items():
                        enabled = self.connection_choices.setdefault(
                            key, spec.get("auto_connect", True)
                        )
                        spec["connection_enabled"] = enabled
                await asyncio.to_thread(self.robots.sync)
            self.start_cameras(room)
            feedback = self.robots.report()
            robots = []
            for key, spec in self.local.robots.items():
                connection = {}
                try:
                    managed = getattr(adapter_type(spec["kind"]), "manages_connection", False)
                    connection = {"connection_enabled": spec.get("connection_enabled", not managed)}
                    controller = self.controller(key)
                    state = {"controller": await controller.status()} if controller else {}
                    if controller and state["controller"]["status"] != "running":
                        if error := self.controller_errors.get(key):
                            state["controller"].update(status="error", error=error)
                except (KeyError, ValueError) as exc:
                    state = {"controller": {"status": "unavailable", "error": str(exc)}}
                robots.append(
                    {
                        **{k: v for k, v in spec.items() if k != "controller"},
                        **feedback.get(key, {}),
                        **state,
                        **connection,
                    }
                )
            inventory = self.local.inventory()
            for camera in inventory["cameras"]:
                if error := self.start_errors.get(camera["id"]):
                    camera.update(status="error", error=error)
                elif camera["id"] in self.camera_starts and camera.get("status") == "stopped":
                    camera["status"] = "starting"
            return {
                **inventory,
                "robots": robots,
                "sdk": require_sdk().__version__,
                "simulation_support": await asyncio.to_thread(simulation_support),
                **room,
                **({"cameras": [], "robots": []} if self.room and self.room.changing else {}),
            }
        if action == "simulation.log" and self.room:
            return await self.room.log()
        if action == "camera.log":
            return await self.local.camera_log(params["id"])
        if self.room and self.room.changing and action != "robot.release":
            raise RuntimeError("Wait for the node to finish changing environments")
        if action in {"robot.connect", "robot.disconnect"}:
            key = params["id"]
            async with self.controller_lock:
                await self.set_connection(key, action == "robot.connect")
            return await self.call("inventory")
        if action in {"robot.start", "robot.log"}:
            controller = self.controller(params["id"])
            if controller is None:
                raise ValueError("Controller startup is not configured on this node")
            if action == "robot.log":
                return await controller.log()
            async with self.controller_lock:
                feedback = self.robots.report().get(params["id"], {})
                if feedback.get("status") != "online" or feedback.get("stale", True):
                    await controller.start()
                self.controller_errors.pop(params["id"], None)
                await self.set_connection(params["id"], True)
            return True
        if action == "camera.start":
            await self.cancel_camera_start(params["id"])
            self.started_cameras.add(params["id"])
            self.start_errors.pop(params["id"], None)
            await self.local.start_camera(params["id"], params.get("settings"))
        elif action == "camera.stop":
            self.started_cameras.add(params["id"])
            await self.cancel_camera_start(params["id"])
            self.start_errors.pop(params["id"], None)
            await self.local.stop_camera(params["id"])
        elif action == "camera.rename":
            await self.local.rename(params["id"], params["name"])
        elif action.startswith("robot."):
            if action == "robot.feedback":
                return self.robots.report()
            method = action.removeprefix("robot.")
            if method not in {
                "prepare",
                "move",
                "renew",
                "hold",
                "release",
                "state",
                "replay_release",
            }:
                raise ValueError("Unsupported robot operation")
            return await asyncio.wrap_future(self.robots.submit(method, **params))
        else:
            raise ValueError("Unsupported node operation")
        # Camera operations must not replace published controller state with local launch settings.
        return {"cameras": self.local.inventory()["cameras"]}

    async def set_connection(self, key, enabled):
        if hasattr(self, "connection_choices"):
            self.connection_choices[key] = enabled
        spec = self.local.robots[key]
        if self.local.simulation or spec.get("profile"):
            path = self.local.directory / "connections.yaml"
            data = load(path)
            data[key] = enabled
        else:
            path = self.local.directory / "devices.yaml"
            data = load(path)
            saved = next(item for item in data.get("robots", []) if item["id"] == key)
            saved["connection_enabled"] = enabled
        save(path, data)
        self.local.robots[key] = {**spec, "connection_enabled": enabled}
        await asyncio.to_thread(self.robots.sync)

    def controller(self, key):
        spec = self.local.robots.get(key, {})
        if not spec.get("controller"):
            return None
        factory = getattr(adapter_type(spec["kind"]), "controller", None)
        return factory(spec, self.local.directory) if factory else None

    def start_cameras(self, room):
        if not self.started or (room.get("simulation") or {}).get("status") not in (None, "ready"):
            return
        for key, camera in self.local.cameras.items():
            if key in self.started_cameras or camera.get("auto_start") is False:
                continue
            self.started_cameras.add(key)
            if key in self.local.workers:
                continue

            async def start(key=key):
                operation = asyncio.create_task(self.local.start_camera(key))
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    # Finish process creation before stopping it; cancelling in
                    # create_subprocess_exec can otherwise orphan a worker.
                    await asyncio.gather(operation, return_exceptions=True)
                    await self.local.stop_camera(key)
                    raise
                except Exception as exc:
                    self.start_errors[key] = str(exc) or type(exc).__name__
                    logging.warning("Stream %s could not start: %s", key, self.start_errors[key])
                finally:
                    self.camera_starts.pop(key, None)

            self.camera_starts[key] = asyncio.create_task(start())

    async def cancel_camera_start(self, key):
        task = self.camera_starts.pop(key, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def cancel_startup(self):
        for key in list(self.camera_starts):
            await self.cancel_camera_start(key)

    async def disconnect(self):
        # Resume streams interrupted by a patient-link loss after re-admission.
        # Streams the operator stopped stay stopped for this node session.
        self.started_cameras.difference_update(set(self.local.workers) | set(self.camera_starts))
        await self.cancel_startup()
        try:
            if self.robots.devices:
                await asyncio.to_thread(self.robots.close)
        finally:
            for camera in list(self.local.workers):
                await self.local.stop_camera(camera)

    async def close(self):
        self.started = False
        await self.cancel_startup()
        if self.room and self.room.task:
            self.room.task.cancel()
            await asyncio.gather(self.room.task, return_exceptions=True)
        errors = []

        async def cleanup(operation):
            try:
                await operation
            except Exception as exc:
                errors.append(str(exc) or type(exc).__name__)

        if self.robots.devices:
            await cleanup(asyncio.to_thread(self.robots.close))
        await cleanup(self.local.close())
        for key in self.local.robots:
            try:
                controller = self.controller(key)
                if controller:
                    await cleanup(controller.stop())
            except Exception as exc:
                errors.append(str(exc) or type(exc).__name__)
        if self.room:
            await cleanup(self.room.close())
        if errors:
            raise RuntimeError("Node cleanup failed: " + "; ".join(errors))
