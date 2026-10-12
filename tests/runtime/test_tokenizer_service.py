# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A live node switches codecs over TLS while the surgeon keeps one WebRTC session."""

import asyncio
import importlib.util

import pytest
from aiortc import RTCPeerConnection, RTCSessionDescription
from telesurgery.server.application import Application

pytest.importorskip("holoscan")
pytest.importorskip("tensorrt" if importlib.util.find_spec("tensorrt") else "tensorrt_bindings")
pytestmark = [pytest.mark.sdk, pytest.mark.gpu, pytest.mark.asyncio]


async def until(predicate):
    async with asyncio.timeout(60):
        while not predicate():
            await asyncio.sleep(0.05)


async def test_neural_switch_on_direct_node_stream(tmp_path, monkeypatch, enrolled_node):
    cameras = [
        {
            "id": "test",
            "name": "Test",
            "kind": "synthetic",
            "source": "synthetic",
            "width": 1280,
            "height": 720,
            "fps": 30,
        }
    ]
    monkeypatch.setattr("telesurgery.nodes.local.discover", lambda *args: (cameras, []))
    patient = Application("patient", tmp_path / "patient", endpoint_port=0)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    browser = RTCPeerConnection()
    frames = []
    reader = None

    @browser.on("track")
    def on_track(track):
        nonlocal reader

        async def receive():
            while True:
                frame = await track.recv()
                frames.append((frame.width, frame.height, frame.pts))

        reader = asyncio.create_task(receive())

    try:
        await patient.start()
        node, key = await enrolled_node(patient, tmp_path / "node")
        camera = f"{key}:test"
        await patient.action("camera.start", {"id": camera})
        process = node.node.local.workers["test"]["process"]
        await surgeon.start()
        admission = await surgeon.connect(
            f"127.0.0.1:{patient.endpoint_port}", "Trial viewer", False
        )
        await patient.action("access.approve", {"id": admission["id"]})
        await until(lambda: camera in {c["id"] for c in surgeon.remote_status.get("cameras", [])})
        await surgeon.action("view", {"cameras": [camera]})
        browser.addTransceiver("video", direction="recvonly")
        await browser.setLocalDescription(await browser.createOffer())
        answer = await surgeon.media.offer(camera, browser.localDescription.sdp, "offer")
        await browser.setRemoteDescription(RTCSessionDescription(**answer))
        await until(lambda: len(frames) >= 3)
        sequence = -1
        for codec in ("surgical-tokenizer", "h264", "surgical-tokenizer", "h264"):
            await patient.action("camera.start", {"id": camera, "settings": {"codec": codec}})
            await until(lambda codec=codec: surgeon.media.feeds[camera].profile[0] == codec)
            feed = surgeon.media.feeds[camera]
            revision = feed.revision
            await until(lambda feed=feed, revision=revision: feed.revision > revision + 2)
            assert feed.error is None
            header = feed.packet[0]
            assert header["codec"] == "h264"  # Browser conversion, after neural transport.
            assert header["sequence"] > sequence
            sequence = header["sequence"]
            count = len(frames)
            await until(lambda count=count: len(frames) > count + 2)
            assert frames[-1][:2] == (1280, 720)
            assert node.node.local.workers["test"]["process"] is process
            assert process.returncode is None
            assert browser.connectionState == "connected"
        assert all(a[2] < b[2] for a, b in zip(frames, frames[1:], strict=False))
    finally:
        if reader:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        await browser.close()
        await surgeon.close()
        await patient.close()
