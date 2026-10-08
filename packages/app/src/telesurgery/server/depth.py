# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Optional depth side channel, paired to the color video's RTP timestamp."""

import json
import struct

CHUNK = 48 * 1024


class DepthChannel:
    def __init__(self, peer, track):
        self.track, self.channel, self.enabled = track, None, False

        @peer.on("datachannel")
        def opened(channel):
            if channel.label != "depth" or self.channel is not None:
                return
            self.channel = channel

            @channel.on("message")
            def message(raw):
                if not isinstance(raw, str) or len(raw) > 64:
                    return
                try:
                    self.enabled = json.loads(raw).get("enabled") is True
                except (ValueError, AttributeError):
                    pass

    def send(self, timestamp):
        channel, packed = self.channel, self.track.depth
        if not (self.enabled and channel and channel.readyState == "open" and packed):
            return
        # Never queue old depth behind a slow browser. Missing frames remain visibly unavailable.
        if channel.bufferedAmount + len(packed) > 8 * 1024 * 1024:
            return
        count = (len(packed) + CHUNK - 1) // CHUNK
        width, height = self.track.depth_size
        for index in range(count):
            prefix = struct.pack("!IHHHH", timestamp, width, height, index, count)
            channel.send(prefix + packed[index * CHUNK : (index + 1) * CHUNK])
