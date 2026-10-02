# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A dashboard-free device service, paired directly from the patient UI."""

import asyncio
import logging
import secrets
import signal
import socket
import time
from pathlib import Path

from telesurgery.nodes.pairing import fingerprint
from telesurgery.nodes.service import NodeService
from telesurgery.nodes.video import VideoEndpoint
from telesurgery_core.configuration import load, save
from telesurgery_core.diagnostics.clock import Clock
from telesurgery_core.diagnostics.trace import mark, source
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.transport.tls import server_context
from telesurgery_runtime.sdk import require_sdk

LOG = logging.getLogger(__name__)


class NodeServer:
    def __init__(self, directory, port=7448, *, video_port=None):
        self.directory, self.port = Path(directory), port
        self.clock = Clock()
        self.video = VideoEndpoint(self.directory, self.clock)
        self.video_port = video_port if video_port is not None else port + 1 if port else 0
        self.node = NodeService(self.directory, self._video)
        self.peer = self.server = None
        self.peers, self.connections, self.tasks = set(), set(), set()
        self.last_request = 0.0
        self.ready = False

    async def start(self, environment=None, sim_gui=False):
        context = server_context(self.directory)
        path = self.directory / "service.yaml"
        config = load(path) or {"token": secrets.token_urlsafe(32)}
        save(path, config)
        self.token = config["token"]
        self.pairing_code = f"{fingerprint(self.directory)}.{self.token}"
        await self.node.start(environment, sim_gui)
        await self.video.start(self.video_port)
        self.server = await asyncio.start_server(self._accept, "0.0.0.0", self.port, ssl=context)
        self.port = self.server.sockets[0].getsockname()[1]
        self.tasks = {asyncio.create_task(self.clock.watch()), asyncio.create_task(self._watch())}

    async def _video(self, camera, header, payload):
        trace = mark(source(VideoHeader(**header)), "source_relay_ms")
        self.video.publish(camera, header, payload, trace)

    async def _request(self, peer, method, params):
        if method == "node.info":
            return {"name": socket.gethostname(), "sdk": require_sdk().__version__}
        if method == "node.attach":
            token = params.get("token")
            if not isinstance(token, str) or not secrets.compare_digest(token, self.token):
                raise PermissionError("Incorrect pairing code")
            if self.peer is not None:
                raise PermissionError("Node is already connected to a patient")
            self.peer = peer
            self.last_request = time.monotonic()
            before = time.time()
            reply = await peer.call("node.time", timeout=5)
            self.node.robots.clock_offset = reply["server_time"] - (before + time.time()) / 2
            inventory = await self.node.call("inventory")
            self.ready = True
            LOG.info("Patient connected")
            return {**inventory, "video": self.video.address}
        if peer is not self.peer or not self.ready:
            raise PermissionError("Pair this node with the patient before accessing devices")
        self.last_request = time.monotonic()
        if method == "environment.set":
            raise PermissionError("Restart this node with --sim to change its environment")
        if method.startswith("video."):
            return await self.video.control(method, params)
        if method == "camera.stop":
            await self.video.revoke(cameras={params["id"]})
        result = await self.node.call(method, params)
        return {**result, "video": self.video.address} if method == "inventory" else result

    async def _accept(self, reader, writer):
        if len(self.peers) >= 8:
            writer.close()
            return
        task = asyncio.current_task()
        self.connections.add(task)
        peer = Peer(
            reader,
            writer,
            self._request,
            clock=self.clock,
        ).start()
        self.peers.add(peer)
        try:
            try:
                await asyncio.wait_for(peer.closed.wait(), 10)
            except TimeoutError:
                if peer is self.peer and self.ready:
                    await peer.closed.wait()
        finally:
            await peer.close()
            if peer is self.peer:
                self.ready = False
                await self.video.revoke()
                # Keep the connection reserved until cameras stop and controllers hold.
                try:
                    await self.node.disconnect()
                except Exception:
                    LOG.exception("Device cleanup failed after patient disconnect")
                finally:
                    self.peer = None
                LOG.info("Patient disconnected")
            self.peers.discard(peer)
            self.connections.discard(task)

    async def _watch(self):
        while True:
            try:
                await self.node.call("robot.expire")
                if self.peer and time.monotonic() - self.last_request > 15:
                    await self.peer.close()
            except Exception:
                LOG.exception("Node watchdog failed")
            await asyncio.sleep(0.1)

    async def close(self):
        if self.server:
            self.server.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for peer in list(self.peers):
            await peer.close()
        await asyncio.gather(*self.connections, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()
        await self.video.close()
        await self.node.close()


async def run_service(directory, port, environment=None, sim_gui=False):
    service = NodeServer(directory, port)
    try:
        await service.start(environment, sim_gui)
        task = asyncio.current_task()
        for number in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(number, task.cancel)
        print(f"Node service: {socket.gethostname()}:{service.port}", flush=True)
        print(f"Pairing code: {service.pairing_code}", flush=True)
        print("Patient dashboard → Nodes → Add node → Connect running service", flush=True)
        await asyncio.Event().wait()
    finally:
        await service.close()
