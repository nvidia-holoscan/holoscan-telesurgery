# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Direct node video, authorized by short-lived tickets from the patient service."""

import asyncio
import secrets
import time

from telesurgery.nodes.address import fingerprint
from telesurgery_core.diagnostics.benchmark import Benchmark
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.transport.tls import server_context


class VideoEndpoint:
    def __init__(self, directory, clock):
        self.directory, self.clock = directory, clock
        self.tickets, self.viewers = {}, {}
        self.metrics = {}
        self.peers, self.connections = set(), set()
        self.server = None

    async def start(self, port=7449):
        self.server = await asyncio.start_server(
            self._accept,
            "0.0.0.0",  # TLS and one-use viewer tickets. # nosec B104
            port,
            ssl=server_context(self.directory),
            ssl_handshake_timeout=10,
        )
        self.address = {
            "port": self.server.sockets[0].getsockname()[1],
            "fingerprint": fingerprint(self.directory),
        }

    async def control(self, method, params):
        if method == "video.metrics":
            camera = params.get("camera")
            items = tuple(self.metrics.items())
            return await asyncio.to_thread(
                lambda: {
                    key: value.report() for key, value in items if camera is None or key == camera
                }
            )
        if method == "video.reset":
            for key, value in self.metrics.items():
                if params.get("camera") in (None, key):
                    value.reset()
            return True
        if method == "video.ticket":
            self.tickets = {
                k: v for k, v in self.tickets.items() if v["expires"] > time.monotonic()
            }
            if len(self.tickets) >= 64:
                raise RuntimeError("Too many pending video connections")
            token = secrets.token_urlsafe(32)
            self.tickets[token] = {**params, "expires": time.monotonic() + 30}
            return {**self.address, "ticket": token}
        if method == "video.revoke":
            await self.revoke(params["owner"], params.get("cameras"))
            return True
        raise ValueError("Unsupported video operation")

    async def _request(self, peer, method, params):
        if method != "viewer.attach" or peer.id in self.viewers:
            raise PermissionError("Video connections accept a single viewer ticket")
        ticket = self.tickets.pop(params.get("ticket"), None)
        if ticket is None or ticket["expires"] < time.monotonic():
            raise PermissionError("Video ticket expired or is invalid")
        self.viewers[peer.id] = ticket
        return True

    async def _accept(self, reader, writer):
        if len(self.peers) >= 64:
            writer.close()
            return
        task = asyncio.current_task()
        self.connections.add(task)
        peer = Peer(
            reader, writer, self._request, clock=self.clock, video_sent=self.sent, max_payload=0
        ).start()
        self.peers.add(peer)
        try:
            try:
                await asyncio.wait_for(peer.closed.wait(), 10)
            except TimeoutError:
                if peer.id in self.viewers:
                    await peer.closed.wait()
        finally:
            self.viewers.pop(peer.id, None)
            await peer.close()
            self.peers.discard(peer)
            self.connections.discard(task)

    def sent(self, camera, trace, frame_bytes):
        key = camera.split(":", 1)[-1]
        if key in self.metrics:
            self.metrics[key].add("transport_frame_bytes", frame_bytes)
            self.metrics[key].finish(trace, "send")

    def publish(self, camera, header, payload, trace):
        if camera not in self.metrics:
            self.metrics[camera] = Benchmark()
        metrics = self.metrics[camera]
        parsed = VideoHeader(**header)
        metrics.observe(parsed)
        metrics.encoded(parsed, payload)
        for peer in self.peers:
            ticket = self.viewers.get(peer.id)
            if ticket and ticket["camera"] == camera and not peer.closed.is_set():
                peer.event(
                    "video",
                    {"camera": ticket["id"], "header": header, "trace": trace},
                    payload,
                    stream=camera,
                )

    async def revoke(self, owner=None, cameras=None):
        def matches(item):
            return (owner is None or item["owner"] == owner) and (
                cameras is None or item["camera"] in cameras
            )

        self.tickets = {k: v for k, v in self.tickets.items() if not matches(v)}
        for peer in list(self.peers):
            if matches(self.viewers.get(peer.id, {"owner": None, "camera": None})):
                self.viewers.pop(peer.id, None)
                await peer.close()

    async def close(self):
        if self.server:
            self.server.close()
        self.tickets.clear()
        for peer in list(self.peers):
            await peer.close()
        await asyncio.gather(*self.connections, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()
