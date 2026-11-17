# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A dashboard asks a camera for one IDR at a time, however often a browser reports loss."""

import asyncio

import pytest
from telesurgery.server.streams import DirectStreams

pytestmark = pytest.mark.asyncio


async def test_keyframe_requests_for_a_camera_do_not_pile_up():
    calls, release = [], asyncio.Event()

    class Peer:
        closed = asyncio.Event()

        async def call(self, method, params, timeout):
            calls.append(method)
            await release.wait()
            return True

    streams = DirectStreams(app=None)
    streams.peers["camera"] = Peer()
    for _ in range(100):  # One NACK can list many packets while the link is lossy.
        streams.refresh("camera")
    streams.refresh("unknown")
    await asyncio.sleep(0)
    assert calls == ["viewer.refresh"]
    release.set()
    await asyncio.gather(*streams.refreshing.values())
    await asyncio.sleep(0)
    assert not streams.refreshing
    streams.refresh("camera")
    await asyncio.sleep(0)
    assert calls == ["viewer.refresh"] * 2
