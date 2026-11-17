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
from telesurgery_core.video.reference import ReferenceChain

# At most one forced IDR per camera in this window, however many viewers ask.
KEYFRAME_COALESCE = 0.1


class VideoEndpoint:
    def __init__(self, directory, clock):
        self.directory, self.clock = directory, clock
        self.tickets, self.viewers = {}, {}
        self.metrics = {}
        self.peers, self.connections = set(), set()
        self.server = None
        self.refresh = lambda camera: None  # Set by the node: force an IDR for this camera.
        # Per camera: last forced IDR, latest request, last IDR published, pending retry.
        self.refreshed, self.asked, self.keyframes, self.deferred = {}, {}, {}, {}
        self.waiting = set()  # Viewers (peer ids) that need an IDR before further deltas.
        self.chains = {}  # Per camera: continuity of the frames its worker delivers.

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
        if method == "viewer.refresh" and peer.id in self.viewers:
            self.keyframe(self.viewers[peer.id]["camera"])
            return True
        if method != "viewer.attach" or peer.id in self.viewers:
            raise PermissionError("Video connections accept a single viewer ticket")
        ticket = self.tickets.pop(params.get("ticket"), None)
        if ticket is None or ticket["expires"] < time.monotonic():
            raise PermissionError("Video ticket expired or is invalid")
        self.viewers[peer.id] = ticket
        # A new viewer cannot decode predicted frames until the next IDR.
        self.keyframe(ticket["camera"])
        return True

    def keyframe(self, camera):
        """Force an IDR for a viewer that cannot decode.

        Viewers that lost the same frame share one IDR. A request inside the window
        is retried when the window ends, unless an IDR has been published since.
        """
        now = time.monotonic()
        self.asked[camera] = now
        wait = self.refreshed.get(camera, -1.0) + KEYFRAME_COALESCE - now
        if wait <= 0:
            self.refreshed[camera] = now
            self.refresh(camera)
        elif camera not in self.deferred:
            self.deferred[camera] = asyncio.get_running_loop().call_later(
                wait, self._retry_keyframe, camera
            )

    def _retry_keyframe(self, camera):
        self.deferred.pop(camera, None)
        if self.asked.get(camera, 0.0) > self.keyframes.get(camera, 0.0):
            self.keyframe(camera)

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
            self.waiting.discard(peer.id)
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
        if parsed.keyframe:
            self.keyframes[camera] = time.monotonic()
        if not self.chains.setdefault(camera, ReferenceChain()).accept(parsed):
            # A frame was lost between the encoder and this node, so no viewer can
            # decode this one. Ask now instead of waiting for each viewer to notice.
            metrics.add("withheld_frames", 1)
            self.keyframe(camera)
            return
        for peer in self.peers:
            ticket = self.viewers.get(peer.id)
            if ticket and ticket["camera"] == camera and not peer.closed.is_set():
                if parsed.keyframe:
                    self.waiting.discard(peer.id)  # Replaces whatever is still unsent.
                elif peer.id in self.waiting or camera in peer.frames:
                    # This viewer is behind: the frame before this one is unsent or was
                    # skipped. Keep the queued frame, which still decodes, withhold
                    # deltas that cannot, and get the viewer a new IDR. A slow link
                    # then shows IDRs at the rate it can carry instead of freezing.
                    self.waiting.add(peer.id)
                    metrics.add("withheld_frames", 1)
                    self.keyframe(camera)
                    continue
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
        for timer in self.deferred.values():
            timer.cancel()
        self.deferred.clear()
        for peer in list(self.peers):
            await peer.close()
        await asyncio.gather(*self.connections, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()
