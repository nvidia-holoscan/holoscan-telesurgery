# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A browser track follows IPPP loss rules without a GPU."""

import asyncio
from dataclasses import asdict

import pytest
from telesurgery.server.media import EncodedTrack, Feed, Media
from telesurgery_core.transport.protocol import VideoHeader

pytestmark = pytest.mark.asyncio


def packet(index, gop=1):
    header = VideoHeader(
        index, 1_000 + index, 64, 64, keyframe=index == 0, gop=gop, gop_index=index
    )
    return asdict(header), b"frame%d" % index


async def test_track_skips_deltas_until_a_keyframe_and_asks_for_one():
    requests = []
    feed = Feed(lambda: requests.append("idr"))
    track = EncodedTrack(feed)

    async def publish(index, gop=1):
        await feed.put(*packet(index, gop))

    async def next_data():
        return bytes(await asyncio.wait_for(track.recv(), 2))

    # Joined mid-GOP: the delta is withheld and exactly one IDR is requested.
    await publish(4)
    receiving = asyncio.create_task(next_data())
    await asyncio.sleep(0.05)
    assert not receiving.done() and requests == ["idr"]
    await publish(5)
    await asyncio.sleep(0.05)
    assert not receiving.done() and requests == ["idr"]  # Paced, not one per frame.
    await publish(0, gop=2)
    assert await receiving == b"frame0"
    await publish(1, gop=2)
    assert await next_data() == b"frame1"
    # The feed holds only the newest frame, so a slow track can miss one.
    await publish(2, gop=2)
    await publish(3, gop=2)
    receiving = asyncio.create_task(next_data())
    await asyncio.sleep(0.05)
    assert not receiving.done()
    track.chain.next_request = 0
    await publish(4, gop=2)
    await asyncio.sleep(0.05)
    assert requests == ["idr", "idr"]
    await publish(0, gop=3)
    assert await receiving == b"frame0"


async def test_media_routes_keyframe_requests_to_its_owner_by_camera():
    asked = []
    media = Media(refresh=asked.append)
    await media.put("one", *packet(0))
    feed = media.feeds["one"]
    feed.request_keyframe()
    assert asked == ["one"]
    assert media.feed("one") is feed
