# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Device discovery and control on a local or remote device node."""

import asyncio

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

    async def start(self, environment=None, sim_gui=False):
        if environment:
            self.room.start(environment, sim_gui)
        await self.call("inventory")

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
                await asyncio.to_thread(self.robots.sync)
            feedback = self.robots.report()
            robots = []
            for key, spec in self.local.robots.items():
                connection = {}
                try:
                    managed = getattr(adapter_type(spec["kind"]), "manages_connection", False)
                    connection = {"connection_enabled": spec.get("connection_enabled", not managed)}
                    controller = self.controller(key)
                    state = {"controller": await controller.status()} if controller else {}
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
            return {
                **self.local.inventory(),
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
            if params.get("confirmed") is not True:
                raise PermissionError(
                    "Confirm an operator is present before starting the controller"
                )
            async with self.controller_lock:
                feedback = self.robots.report().get(params["id"], {})
                if feedback.get("status") != "online" or feedback.get("stale", True):
                    await controller.start()
                await self.set_connection(params["id"], True)
            return True
        if action == "camera.start":
            await self.local.start_camera(params["id"], params.get("settings"))
        elif action == "camera.stop":
            await self.local.stop_camera(params["id"])
        elif action == "camera.rename":
            await self.local.rename(params["id"], params["name"])
        elif action.startswith("robot."):
            if action == "robot.feedback":
                return self.robots.report()
            method = action.removeprefix("robot.")
            if method not in {"prepare", "move", "renew", "release", "state"}:
                raise ValueError("Unsupported robot operation")
            return await asyncio.wrap_future(self.robots.submit(method, **params))
        else:
            raise ValueError("Unsupported node operation")
        # Camera operations must not replace published controller state with local launch settings.
        return {"cameras": self.local.inventory()["cameras"]}

    async def set_connection(self, key, enabled):
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

    async def disconnect(self):
        try:
            if self.robots.devices:
                await asyncio.to_thread(self.robots.close)
        finally:
            for camera in list(self.local.workers):
                await self.local.stop_camera(camera)

    async def close(self):
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
