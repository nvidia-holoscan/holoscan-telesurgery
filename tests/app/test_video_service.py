# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""GPU H.264 reaches a browser-compatible decoder; the live service stops cleanly."""

import asyncio
import os
import socket
import subprocess
import sys

import aiohttp
import pytest
from aiortc import RTCPeerConnection, RTCRtpSender, RTCSessionDescription
from telesurgery_core.configuration import save

pytestmark = [pytest.mark.sdk, pytest.mark.gpu, pytest.mark.asyncio]


async def test_live_video_and_shutdown(tmp_path):
    workspace = tmp_path / "workspace"
    host = workspace / "nodes" / socket.gethostname()
    host.mkdir(parents=True)
    save(
        host / "devices.yaml",
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
        },
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
            "--workspace",
            str(workspace),
        ],
        stdout=log,
        stderr=log,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    node_log = (tmp_path / "node.log").open("w")
    node_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "telesurgery",
            "node",
            "--patient",
            f"127.0.0.1:{endpoint}",
            "--workspace",
            str(workspace),
        ],
        stdout=node_log,
        stderr=node_log,
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
            async with asyncio.timeout(20):
                while True:
                    async with http.get(url + "/api/status") as response:
                        state = await response.json()
                    if state["node_requests"]:
                        break
                    await asyncio.sleep(0.05)
            key = state["node_requests"][0]["id"]
            async with http.post(
                url + "/api/action", json={"action": "node.approve", "params": {"id": key}}
            ) as response:
                assert response.status == 200
            async with asyncio.timeout(20):
                while True:
                    async with http.get(url + "/api/status") as response:
                        state = await response.json()
                    if any(c["id"] == f"{key}:test" for c in state["cameras"]):
                        break
                    await asyncio.sleep(0.05)
            async with http.post(
                url + "/api/action",
                json={
                    "action": "camera.start",
                    "params": {"id": f"{key}:test", "settings": {"codec": "h264"}},
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
                json={
                    "camera": f"{key}:test",
                    "sdp": browser.localDescription.sdp,
                    "type": "offer",
                },
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
        if node_process.poll() is None:
            node_process.terminate()
            try:
                await asyncio.to_thread(node_process.wait, timeout=15)
            except subprocess.TimeoutExpired:
                node_process.kill()
                node_process.wait(timeout=5)
        node_log.close()
        log.close()
