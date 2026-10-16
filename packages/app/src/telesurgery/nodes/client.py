# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Device nodes request patient approval, then serve control and direct video."""

import asyncio
import contextlib
import logging
import secrets
import signal
import time
from pathlib import Path

from telesurgery.nodes.address import endpoint
from telesurgery.nodes.service import NodeService
from telesurgery.nodes.video import VideoEndpoint
from telesurgery_core.configuration import load, save
from telesurgery_core.diagnostics.clock import Clock
from telesurgery_core.diagnostics.trace import mark, source
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.transport.tls import client_context, pin_peer

LOG = logging.getLogger(__name__)


class NodeClient:
    def __init__(self, directory, config, environment=None, sim_gui=False):
        self.started_at = time.monotonic()
        self.directory, self.config = Path(directory), config
        self.environment, self.sim_gui = environment, sim_gui
        self.clock = Clock()
        self.video = VideoEndpoint(self.directory, self.clock)
        self.node = NodeService(self.directory, self.publish)
        self.peer = None
        self.ready = self.started = self.removed = False
        self.last_status = ""

    async def publish(self, camera, header, payload):
        trace = mark(source(VideoHeader(**header)), "source_relay_ms")
        self.video.publish(camera, header, payload, trace)

    async def request(self, peer, method, params):
        if not self.ready:
            raise PermissionError("Patient approval is required before accessing devices")
        if method == "node.remove":
            self.removed = True
            return True
        if method == "node.log":
            from telesurgery_core.diagnostics.logs import read_log

            return await asyncio.to_thread(read_log, self.directory / "node.log")
        if method == "environment.set":
            raise PermissionError("Restart this node with --sim to change its environment")
        if method.startswith("video."):
            return await self.video.control(method, params)
        if method == "camera.stop":
            await self.video.revoke(cameras={params["id"]})
        result = await self.node.call(method, params)
        return result

    async def feedback(self):
        while True:
            if self.ready and self.peer and not self.peer.closed.is_set():
                self.peer.event(
                    "robot.feedback", self.node.robots.report(), stream="robot.feedback"
                )
            await asyncio.sleep(0.1)

    async def connect(self):
        config = self.config
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(config["host"], config["port"], ssl=client_context()), 5
        )
        try:
            pin_peer(
                writer,
                f"{config['host']}:{config['port']}",
                self.directory,
                config.get("fingerprint"),
            )
        except BaseException:
            writer.close()
            await writer.wait_closed()
            raise
        self.peer = Peer(reader, writer, self.request, clock=self.clock, max_payload=0).start()
        while True:
            reply = await self.peer.call(
                "node.request",
                {
                    "name": config["name"],
                    "token": config["token"],
                    "environment": self.environment,
                },
            )
            status = reply["status"]
            if status != self.last_status:
                LOG.info("Patient admission: %s", status)
                self.last_status = status
            if status == "rejected":
                raise PermissionError("Patient rejected this node request")
            if status == "approved":
                key = reply["id"]
                break
            await asyncio.sleep(1)
        if not self.started:
            await self.node.start(self.environment, self.sim_gui)
            await self.video.start(config.get("video_port", 0))
            self.started = True
        inventory = await self.inventory()
        before = time.time()
        registered = await self.peer.call(
            "node.register",
            {
                "id": key,
                "token": config["token"],
                "inventory": inventory,
            },
        )
        self.node.robots.clock_offset = registered["server_time"] - (before + time.time()) / 2
        self.ready = True
        LOG.info("Connected to patient at %s:%s", config["host"], config["port"])

    async def inventory(self):
        return {
            **await self.node.call("inventory"),
            "name": self.config["name"],
            "video": self.video.address,
            "uptime_s": max(0, int(time.monotonic() - self.started_at)),
        }

    async def run(self):
        tasks = [asyncio.create_task(self.clock.watch()), asyncio.create_task(self.feedback())]
        try:
            while not self.removed:
                try:
                    await self.connect()
                    while not self.removed and not self.peer.closed.is_set():
                        inventory = await self.inventory()
                        before = time.time()
                        reply = await self.peer.call("node.inventory", {"inventory": inventory})
                        self.node.robots.clock_offset = (
                            reply["server_time"] - (before + time.time()) / 2
                        )
                        try:
                            await asyncio.wait_for(self.peer.closed.wait(), 2)
                        except TimeoutError:
                            pass
                except PermissionError:
                    raise
                except (ConnectionError, OSError, RuntimeError, TimeoutError) as exc:
                    LOG.warning("Patient connection: %s", exc)
                finally:
                    self.ready = False
                    if self.peer:
                        await self.peer.close()
                    await self.video.revoke()
                    with contextlib.suppress(Exception):
                        await self.node.disconnect()
                await asyncio.sleep(2)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await self.video.close()
            finally:
                await self.node.close()


async def run_service(directory, patient, name, video_port=0, environment=None, sim_gui=False):
    host, port, _ = endpoint(patient, 7447)
    identity = load(directory / "identity.yaml") or {"token": secrets.token_urlsafe(32)}
    save(directory / "identity.yaml", identity)
    config = {**identity, "name": name, "host": host, "port": port, "video_port": video_port}
    print(
        f"Requesting access to patient at {patient}. Approve this node in Patient → Nodes.",
        flush=True,
    )
    await _run(NodeClient(directory, config, environment, sim_gui))


async def _run(client):
    task = asyncio.current_task()
    stopping = False

    def stop():
        nonlocal stopping
        # A second stop request must not cancel the cleanup started by the first.
        if not stopping:
            stopping = True
            task.cancel()

    for number in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(number, stop)
    await client.run()
