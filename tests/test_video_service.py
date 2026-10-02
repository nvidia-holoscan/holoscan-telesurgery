# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""GPU H.264 reaches a browser-compatible decoder; the live service stops cleanly."""

import asyncio
import json
import os
import socket
import subprocess
import sys

import aiohttp
import pytest
from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription

pytestmark = [pytest.mark.sdk, pytest.mark.gpu, pytest.mark.asyncio]


async def test_live_video_and_shutdown(tmp_path):
    state = tmp_path / "patient"
    host = state / "host"
    host.mkdir(parents=True)
    (host / "devices.json").write_text(
        json.dumps(
            {
                "cameras": [
                    {
                        "id": "test",
                        "name": "Test scene",
                        "kind": "synthetic",
                        "source": "synthetic",
                        "width": 320,
                        "height": 240,
                        "fps": 30,
                    }
                ]
            }
        )
    )
    with socket.socket() as a, socket.socket() as b:
        a.bind(("127.0.0.1", 0))
        b.bind(("127.0.0.1", 0))
        port, endpoint = a.getsockname()[1], b.getsockname()[1]
    log = (tmp_path / "service.log").open("w")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "telesurgery",
            "patient",
            "--port",
            str(port),
            "--endpoint-port",
            str(endpoint),
            "--state-dir",
            str(state),
        ],
        stdout=log,
        stderr=log,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    browser = RTCPeerConnection()
    ready = asyncio.Future()

    @browser.on("track")
    def track_received(track):
        async def receive():
            try:
                ready.set_result(await track.recv())
            except Exception as exc:
                if not ready.done():
                    ready.set_exception(exc)

        asyncio.create_task(receive())

    try:
        async with aiohttp.ClientSession() as http:
            async with asyncio.timeout(20):
                while True:
                    assert process.poll() is None, (tmp_path / "service.log").read_text()
                    try:
                        async with http.get(f"http://localhost:{port}/api/status") as response:
                            if response.status == 200:
                                break
                    except aiohttp.ClientConnectionError:
                        pass
                    await asyncio.sleep(0.1)
            url = f"http://localhost:{port}"
            async with http.post(
                url + "/api/action",
                json={
                    "action": "camera.start",
                    "params": {"id": "host:test", "settings": {"codec": "h264"}},
                },
            ) as response:
                assert response.status == 200, await response.text()
            async with http.post(
                url + "/api/action", json={}, headers={"Origin": "https://elsewhere.invalid"}
            ) as response:
                assert response.status == 403
            transceiver = browser.addTransceiver("video", direction="recvonly")
            transceiver.setCodecPreferences(
                [
                    c
                    for c in RTCRtpSender.getCapabilities("video").codecs
                    if c.mimeType == "video/H264"
                ]
            )
            await browser.setLocalDescription(await browser.createOffer())
            async with http.post(
                url + "/api/offer",
                json={"camera": "host:test", "sdp": browser.localDescription.sdp, "type": "offer"},
            ) as response:
                assert response.status == 200, await response.text()
                answer = await response.json()
            await browser.setRemoteDescription(RTCSessionDescription(**answer))
            frame = await asyncio.wait_for(ready, 15)
            assert (frame.width, frame.height) == (320, 240)
            assert frame.to_ndarray(format="rgb24").std() > 10
            process.terminate()
            try:
                code = await asyncio.to_thread(process.wait, timeout=12)
            except subprocess.TimeoutExpired:
                pytest.fail("Service shutdown hung:\n" + (tmp_path / "service.log").read_text())
            assert code == 0, (tmp_path / "service.log").read_text()
    finally:
        await browser.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log.close()
