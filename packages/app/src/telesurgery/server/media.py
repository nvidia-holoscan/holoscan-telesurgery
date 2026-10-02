# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Track encoded streams; forward H.264 to browsers without transcoding."""

import asyncio
import json
import time
from fractions import Fraction

import av
from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
)
from aiortc.mediastreams import MediaStreamError
from telesurgery.server.stream_timing import StreamTiming
from telesurgery_core.diagnostics.benchmark import Benchmark
from telesurgery_core.diagnostics.trace import mark
from telesurgery_core.transport.protocol import decode_video


class Feed:
    def __init__(self):
        self.packet = None
        self.revision = 0
        self.changed = asyncio.Condition()
        self.benchmark = Benchmark()
        self.trace = None

    async def put(self, header, payload, timing=None):
        async with self.changed:
            parsed, payload = decode_video([json.dumps(header).encode(), payload])
            self.benchmark.observe(parsed)
            self.benchmark.encoded(parsed, payload)
            if timing and "status" in timing:
                self.benchmark.delivery(timing)
                self.benchmark.add(
                    "receiver_queue_ms", (time.monotonic_ns() - timing["received_ns"]) / 1e6
                )
            trace = timing.get("trace") if timing else None
            self.trace = (
                mark(trace, "receiver_queue_ms") if timing and "status" in timing else trace
            )
            self.packet = header, payload
            self.revision += 1
            self.changed.notify_all()


class EncodedTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, feed):
        super().__init__()
        self.feed, self.revision, self.origin = feed, -1, None
        self.trace, self.pts = None, None

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        async with self.feed.changed:
            await self.feed.changed.wait_for(
                lambda: self.feed.packet is not None and self.feed.revision != self.revision
            )
            header, data = self.feed.packet
            if header["codec"] != "h264":
                raise MediaStreamError("Use Holoviz for this codec")
            self.trace = self.feed.trace
            self.revision = self.feed.revision
        timestamp = header["captured_ns"]
        if self.origin is None:
            self.origin = timestamp
        packet = av.Packet(data)
        packet.pts = packet.dts = max(0, (timestamp - self.origin) * 90000 // 1_000_000_000)
        packet.time_base = Fraction(1, 90000)
        self.pts = packet.pts
        return packet


class Media:
    def __init__(self, on_change=None):
        self.on_change = on_change
        self.feeds = {}
        self.connections = {}

    async def put(self, camera, header, payload, timing=None):
        if camera not in self.feeds:
            self.feeds[camera] = Feed()
        await self.feeds[camera].put(header, payload, timing)

    async def offer(self, camera, sdp, kind):
        feed = self.feeds.get(camera)
        if feed and feed.packet and feed.packet[0]["codec"] != "h264":
            raise ValueError("Browser preview requires H.264; use Holoviz for this stream")
        if len(self.connections) >= 32:
            raise ValueError("Too many browser video connections")
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.connections[peer] = camera
        if self.on_change:
            await self.on_change()

        @peer.on("connectionstatechange")
        async def state_changed():
            if peer.connectionState in {"failed", "closed"}:
                self.connections.pop(peer, None)
                await peer.close()
                if self.on_change:
                    await self.on_change()

        try:
            transceiver = peer.addTransceiver("video", direction="sendonly")
            codecs = [
                c
                for c in RTCRtpSender.getCapabilities("video").codecs
                if c.mimeType == "video/H264"
            ]
            transceiver.setCodecPreferences(codecs)
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=kind))
            track = EncodedTrack(self.feeds.setdefault(camera, Feed()))
            sender = peer.addTrack(track)
            StreamTiming(peer, track, sender)
            await peer.setLocalDescription(await peer.createAnswer())
            return {"sdp": peer.localDescription.sdp, "type": peer.localDescription.type}
        except BaseException:
            self.connections.pop(peer, None)
            await peer.close()
            if self.on_change:
                await self.on_change()
            raise

    def statistics(self, camera=None):
        return {
            key: feed.benchmark.report()
            for key, feed in tuple(self.feeds.items())
            if camera is None or key == camera
        }

    async def clear(self, camera=None):
        peers = [peer for peer, key in self.connections.items() if camera is None or key == camera]
        for peer in peers:
            self.connections.pop(peer, None)
        await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
        if camera is None:
            self.feeds.clear()
        else:
            self.feeds.pop(camera, None)
