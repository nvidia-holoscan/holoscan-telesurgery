# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Forward H.264, or convert neural tokens once per camera for browser viewing."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
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
from telesurgery.server.depth import DepthChannel
from telesurgery.server.stream_timing import StreamTiming
from telesurgery.server.tokenizer_preview import TokenizerPreview
from telesurgery_core.diagnostics.benchmark import Benchmark
from telesurgery_core.diagnostics.trace import mark
from telesurgery_core.transport.protocol import VideoHeader, decode_video
from telesurgery_core.video.depth import split


class Feed:
    def __init__(self):
        self.packet = None
        self.revision = 0
        self.changed = asyncio.Condition()
        self.benchmark = Benchmark()
        self.trace = None
        self.pending = None
        self.task = self.executor = self.preview = None
        self.generation = 0
        self.profile = None
        self.error = None
        self.closed = False

    async def put(self, header, payload, timing=None):
        if self.closed:
            return
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
            trace = mark(trace, "receiver_queue_ms") if timing and "status" in timing else trace
            profile = parsed.codec, parsed.codec_profile, parsed.width, parsed.height
            if profile != self.profile:
                self.profile = profile
                self.generation += 1
                self.error = None
            if parsed.codec == "surgical-tokenizer":
                if self.error:
                    return
                self.pending = (parsed, payload, trace, self.generation)
                if self.task is None:
                    self.task = asyncio.create_task(self._convert())
                return
            self.pending = None
            if self.executor is not None and self.task is None:
                self.task = asyncio.create_task(self._convert())
            self.trace = trace
            self.packet = header, payload
            self.revision += 1
            self.changed.notify_all()

    async def _convert(self):
        generation = self.generation
        try:
            if self.executor is None:
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
                self.preview = TokenizerPreview()
            while self.pending is not None and not self.closed:
                header, data, trace, generation = self.pending
                self.pending = None
                result = await asyncio.get_running_loop().run_in_executor(
                    self.executor, self.preview.convert, header, data, trace
                )
                if generation != self.generation or self.closed:
                    continue
                async with self.changed:
                    header, data, self.trace = result
                    self.packet = header, data
                    self.revision += 1
                    self.changed.notify_all()
        except Exception as exc:
            async with self.changed:
                if generation == self.generation:
                    self.error = str(exc)
                    self.pending = None
                self.changed.notify_all()
        finally:
            if self.profile and self.profile[0] != "surgical-tokenizer" and self.executor:
                await asyncio.get_running_loop().run_in_executor(self.executor, self.preview.close)
            self.task = (
                asyncio.create_task(self._convert())
                if self.pending is not None and not self.closed
                else None
            )

    async def close(self):
        self.closed = True
        self.pending = None
        async with self.changed:
            self.changed.notify_all()
        if self.task is not None:
            await self.task
        if self.executor is not None:
            await asyncio.get_running_loop().run_in_executor(self.executor, self.preview.close)
            self.executor.shutdown()
            self.executor = self.preview = None


class EncodedTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, feed):
        super().__init__()
        self.feed, self.revision, self.origin = feed, -1, None
        self.trace, self.pts = None, None
        self.depth, self.depth_size = b"", (0, 0)

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError
        async with self.feed.changed:
            await self.feed.changed.wait_for(
                lambda: (
                    self.feed.closed
                    or self.feed.error
                    or (self.feed.packet is not None and self.feed.revision != self.revision)
                )
            )
            if self.feed.closed or self.feed.error:
                raise MediaStreamError(self.feed.error or "Stream closed")
            header, data = self.feed.packet
            self.depth = b""
            if header.get("depth_bytes"):
                parsed = VideoHeader(**header)
                data, self.depth = split(parsed, data)
                self.depth_size = parsed.width, parsed.height
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
        if feed and feed.error:
            raise ValueError(f"Tokenizer preview failed: {feed.error}")
        if feed and feed.packet and feed.packet[0]["codec"] not in {"h264", "surgical-tokenizer"}:
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
                if camera not in self.connections.values():
                    feed = self.feeds.pop(camera, None)
                    if feed is not None:
                        await feed.close()

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
            depth = DepthChannel(peer, track)
            StreamTiming(peer, track, sender, on_frame=depth.send)
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
            feeds = list(self.feeds.values())
            self.feeds.clear()
        else:
            feed = self.feeds.pop(camera, None)
            feeds = [feed] if feed is not None else []
        await asyncio.gather(*(feed.close() for feed in feeds))
