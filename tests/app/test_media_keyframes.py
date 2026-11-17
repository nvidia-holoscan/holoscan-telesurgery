# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A browser track follows IPPP loss rules without a GPU."""

import asyncio
from dataclasses import asdict

import pytest
from telesurgery.server.media import BACKLOG, EncodedTrack, Feed, Media
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
    track.chain.interval = 3600  # A slow test run must not look like a second request.

    async def publish(index, gop=1):
        await feed.put(*packet(index, gop))

    async def next_data():
        return bytes(await asyncio.wait_for(track.recv(), 2))

    async def consumed():
        # The track has looked at everything published so far.
        async with asyncio.timeout(2):
            while track.revision != feed.revision:
                await asyncio.sleep(0.005)

    # Joined mid-GOP: the delta is withheld and exactly one IDR is requested.
    await publish(4)
    receiving = asyncio.create_task(next_data())
    await consumed()
    assert not receiving.done() and requests == ["idr"]
    await publish(5)
    await consumed()
    assert not receiving.done() and requests == ["idr"]  # Paced, not one per frame.
    await publish(0, gop=2)
    assert await receiving == b"frame0"
    await publish(1, gop=2)
    assert await next_data() == b"frame1"
    # Frames that arrive while the track is busy are sent in order, with no keyframe.
    await publish(2, gop=2)
    await publish(3, gop=2)
    await publish(4, gop=2)
    assert [await next_data() for _ in range(3)] == [b"frame2", b"frame3", b"frame4"]
    assert requests == ["idr"]
    # A backlog longer than the feed keeps loses a frame: wait for a new IDR.
    for index in range(5, 5 + BACKLOG + 1):
        await publish(index, gop=2)
    receiving = asyncio.create_task(next_data())
    await consumed()
    assert not receiving.done()
    track.chain.next_request = 0
    await publish(5 + BACKLOG + 1, gop=2)
    await consumed()
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


@pytest.mark.parametrize("kind", ["PLI", "FIR"])
async def test_browser_picture_loss_reaches_the_camera_encoder(kind):
    """aiortc forwards encoded frames, so its sender cannot make a keyframe itself.

    A real RTCP feedback packet goes through the real RTCRtpSender that
    Media.offer() creates: an aiortc upgrade that renames its private keyframe
    hook fails here instead of silently freezing browsers after packet loss.
    """
    from aiortc import RTCPeerConnection
    from aiortc.rtp import RTCP_PSFB_FIR, RTCP_PSFB_PLI, RtcpPsfbPacket

    asked = []
    media = Media(refresh=asked.append)
    await media.put("camera", *packet(0))
    browser = RTCPeerConnection()
    try:
        browser.addTransceiver("video", direction="recvonly")
        await browser.setLocalDescription(await browser.createOffer())
        offer = browser.localDescription
        await media.offer("camera", offer.sdp, offer.type)
        (server,) = media.connections
        (sender,) = server.getSenders()
        track = sender.track
        assert track.chain.accept(VideoHeader(**packet(0)[0]))
        fmt = RTCP_PSFB_PLI if kind == "PLI" else RTCP_PSFB_FIR
        await sender._handle_rtcp_packet(RtcpPsfbPacket(fmt=fmt, ssrc=1, media_ssrc=sender._ssrc))
        assert asked == ["camera"]
        # Deltas after the lost picture are useless to the browser until the IDR.
        assert not track.chain.accept(VideoHeader(**packet(1)[0]))
    finally:
        await browser.close()
        for connection in tuple(media.connections):
            await connection.close()


async def test_a_packet_the_browser_requests_twice_brings_a_keyframe():
    """The first retransmission was lost too; Chrome would wait seconds before a PLI."""
    from aiortc import RTCPeerConnection
    from aiortc.rtp import RTCP_RTPFB_NACK, RtcpRtpfbPacket

    asked = []
    media = Media(refresh=asked.append)
    await media.put("camera", *packet(0))
    browser = RTCPeerConnection()
    try:
        browser.addTransceiver("video", direction="recvonly")
        await browser.setLocalDescription(await browser.createOffer())
        offer = browser.localDescription
        await media.offer("camera", offer.sdp, offer.type)
        (server,) = media.connections
        (sender,) = server.getSenders()

        async def nack(*lost):
            await sender._handle_rtcp_packet(
                RtcpRtpfbPacket(
                    fmt=RTCP_RTPFB_NACK, ssrc=1, media_ssrc=sender._ssrc, lost=list(lost)
                )
            )

        await nack(100, 101)
        assert asked == []  # A first request is answered by retransmission alone.
        await nack(102)
        await nack(101)
        assert asked == ["camera"]
        # While retransmissions are failing, each further loss gets an IDR at once.
        await nack(103)
        assert asked == ["camera", "camera"]
        # Predicted frames keep flowing: the browser may still be decoding.
        assert sender.track.chain.accept(VideoHeader(**packet(0)[0]))
    finally:
        await browser.close()
        for connection in tuple(media.connections):
            await connection.close()
