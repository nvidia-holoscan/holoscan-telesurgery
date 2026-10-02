# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Device operations shared by the patient host and remote nodes."""

import asyncio
import contextlib
import logging
import signal
import time
from pathlib import Path

from telesurgery.nodes.local import LocalNode
from telesurgery_core.configuration import load
from telesurgery_core.diagnostics.clock import Clock
from telesurgery_core.diagnostics.trace import mark, source
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.transport.tls import client_context, pin_peer
from telesurgery_runtime.pipeline import Executor
from telesurgery_runtime.robots import Robots
from telesurgery_runtime.sdk import require_sdk

LOG = logging.getLogger(__name__)


class NodeService:
    def __init__(self, directory, publish, simulation=None, *, managed=False):
        self.local = LocalNode(directory, publish, simulation)
        self.robots = Robots(lambda: self.local.robots)
        self.executor = Executor("patient_node")
        self.room = None
        if simulation is None:
            from telesurgery.nodes.simulation import NodeSimulation

            self.room = NodeSimulation(self, persist=managed)

    async def start(self, environment=None, sim_gui=False):
        await asyncio.to_thread(self.executor.start)
        if self.room:
            if environment:
                self.room.select(environment, sim_gui)
            else:
                self.room.restore()
        await self.call("inventory")

    async def call(self, action, params=None):
        params = params or {}
        if action == "inventory":
            if not self.room or not (self.room.changing or self.room.error):
                await self.local.refresh()
            return {
                **self.local.inventory(),
                "sdk": require_sdk().__version__,
                **(self.room.status() if self.room else {}),
                **({"cameras": [], "robots": []} if self.room and self.room.changing else {}),
            }
        if action == "simulation.log" and self.room:
            return await self.room.log()
        if action == "environment.set" and self.room:
            self.room.select(params.get("environment"), params.get("gui", False))
            return await self.call("inventory")
        if self.room and self.room.changing and action not in {"robot.expire", "robot.release"}:
            raise RuntimeError("Wait for the node to finish changing environments")
        if action == "camera.start":
            await self.local.start_camera(params["id"], params.get("settings"))
        elif action == "camera.stop":
            await self.local.stop_camera(params["id"])
        elif action == "camera.rename":
            await self.local.rename(params["id"], params["name"])
        elif action.startswith("robot."):
            functions = {
                "robot.prepare": self.robots.prepare,
                "robot.move": self.robots.move,
                "robot.renew": self.robots.renew,
                "robot.release": self.robots.release,
                "robot.state": self.robots.state,
                "robot.expire": self.robots.expire,
            }
            function = functions.get(action)
            if function is None:
                raise ValueError("Unsupported robot operation")
            return await asyncio.wrap_future(
                self.executor.submit(
                    lambda: function(**params), timeout=0.2 if action == "robot.move" else 2
                )
            )
        else:
            raise ValueError("Unsupported node operation")
        return self.local.inventory()

    async def disconnect(self):
        try:
            if self.robots.devices:
                await asyncio.wrap_future(self.executor.submit(self.robots.close))
        finally:
            for camera in list(self.local.workers):
                await self.local.stop_camera(camera)

    async def close(self):
        if self.room and self.room.task:
            self.room.task.cancel()
            await asyncio.gather(self.room.task, return_exceptions=True)
        await self.local.close()
        try:
            if self.robots.devices:
                await asyncio.wrap_future(self.executor.submit(self.robots.close))
        finally:
            await asyncio.to_thread(self.executor.close)
            if self.room:
                await self.room.close()


async def run_node(config_path, environment=None, sim_gui=False):
    config = load(Path(config_path).with_suffix(".yaml"))
    directory = Path(config_path).parent
    from telesurgery.nodes.video import VideoEndpoint

    peer = None
    clock = Clock()
    video_endpoint = VideoEndpoint(directory, clock)

    async def video(camera, header, payload):
        trace = mark(source(VideoHeader(**header)), "source_relay_ms")
        video_endpoint.publish(camera, header, payload, trace)

    node = NodeService(directory, video, config.get("simulation"), managed=True)
    initial = environment
    if initial is None and not load(directory / "environment.yaml"):
        initial = config.get("environment")
    await node.start(initial, sim_gui)
    await video_endpoint.start(config.get("video_port", 7449))
    clock_task = asyncio.create_task(clock.watch())
    main_task = asyncio.current_task()
    for number in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(number, main_task.cancel)

    async def handle(connection, method, params):
        if method.startswith("video."):
            return await video_endpoint.control(method, params)
        if method == "camera.stop":
            await video_endpoint.revoke(cameras={params["id"]})
        result = await node.call(method, params)
        if method == "environment.set":
            await video_endpoint.revoke()
        return result

    async def expire():
        while True:
            try:
                await node.call("robot.expire")
            except Exception:
                LOG.exception("Controller watchdog failed")
            await asyncio.sleep(0.1)

    watchdog = asyncio.create_task(expire())
    try:
        while True:
            try:
                reader, writer = await asyncio.open_connection(
                    config["host"], config["port"], ssl=client_context()
                )
                try:
                    pin_peer(
                        writer,
                        f"{config['host']}:{config['port']}",
                        directory,
                        config.get("fingerprint"),
                    )
                except Exception:
                    writer.close()
                    raise
                peer = Peer(
                    reader,
                    writer,
                    handle,
                    clock=clock,
                ).start()
                before = time.time()
                registered = await peer.call(
                    "node.register",
                    {
                        "id": config["id"],
                        "token": config["token"],
                        "inventory": {
                            **await node.call("inventory"),
                            "video": video_endpoint.address,
                        },
                    },
                )
                node.robots.clock_offset = registered["server_time"] - (before + time.time()) / 2
                while not peer.closed.is_set():
                    await peer.call(
                        "node.inventory",
                        {
                            "inventory": {
                                **await node.call("inventory"),
                                "video": video_endpoint.address,
                            }
                        },
                    )
                    try:
                        await asyncio.wait_for(peer.closed.wait(), 2)
                    except TimeoutError:
                        pass
            except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
                LOG.warning("Patient connection: %s", exc)
            finally:
                if peer:
                    await peer.close()
                await video_endpoint.revoke()
                with contextlib.suppress(Exception):
                    await node.disconnect()
            await asyncio.sleep(2)
    finally:
        watchdog.cancel()
        clock_task.cancel()
        await asyncio.gather(watchdog, clock_task, return_exceptions=True)
        await video_endpoint.close()
        await node.close()
