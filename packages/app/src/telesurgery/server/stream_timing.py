# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Optional RTP timestamp correlation, without changing or copying video payloads.

aiortc exposes no packet-sent observer. Keep its single private transport hook here;
the browser integration test exercises this boundary with real H.264/RTP.
"""

import contextlib
import json
import math
import struct
import time

from aiortc.exceptions import InvalidStateError
from telesurgery_core.diagnostics.trace import mark, wire


class StreamTiming:
    def __init__(self, peer, track, sender, on_frame=None):
        self.track, self.channel = track, None
        self.until = 0
        self.origin = None
        self.last_timestamp = None
        send = sender.transport._send_rtp

        async def send_rtp(data):
            report = None
            frame_timestamp = None
            # RTCP uses the same transport; only observe this video sender's RTP.
            if len(data) >= 12 and 96 <= (data[1] & 127) <= 127:
                timestamp, ssrc = struct.unpack_from("!II", data, 4)
                if ssrc == sender._ssrc and track.pts is not None:
                    if self.origin is None:
                        self.origin = (timestamp - track.pts) & 0xFFFFFFFF
                    expected = (self.origin + track.pts) & 0xFFFFFFFF
                    if timestamp == expected and timestamp != self.last_timestamp:
                        self.last_timestamp = timestamp
                        frame_timestamp = timestamp
                        if time.monotonic() < self.until and self.channel.readyState == "open":
                            trace = mark(track.trace, "browser_queue_ms")
                            if trace:
                                report = {
                                    "type": "frame",
                                    "rtp": timestamp,
                                    "at_ms": trace["at_ns"] / 1e6,
                                    **wire(trace),
                                }
            await send(data)
            if frame_timestamp is not None and on_frame:
                on_frame(frame_timestamp)
            # The unreliable side channel never delays video for an acknowledgement.
            if report and self.channel.readyState == "open" and self.channel.bufferedAmount < 16384:
                with contextlib.suppress(InvalidStateError):
                    self.channel.send(json.dumps(report, separators=(",", ":")))

        sender.transport._send_rtp = send_rtp

        @peer.on("datachannel")
        def channel_open(channel):
            if channel.label != "frame-timing" or self.channel is not None:
                return
            self.channel = channel

            @channel.on("message")
            def message(raw):
                received = time.monotonic_ns() / 1e6
                if not isinstance(raw, str) or len(raw) > 256:
                    return
                try:
                    value = json.loads(raw)
                    if value.get("type") == "watch":
                        self.until = time.monotonic() + 40 if value.get("enabled") else 0
                    elif value.get("type") == "clock" and time.monotonic() < self.until:
                        t0 = value.get("t0")
                        if type(t0) in (float, int) and math.isfinite(t0):
                            channel.send(
                                json.dumps(
                                    {
                                        "type": "clock",
                                        "t0": t0,
                                        "t1": received,
                                        "t2": time.monotonic_ns() / 1e6,
                                    }
                                )
                            )
                except (ValueError, TypeError, AttributeError, InvalidStateError):
                    return
