# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise depth pairing over real WebRTC/SCTP and Chromium frame callbacks."""

import asyncio
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from telesurgery.server.media import Media
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.codecs import CodecWorker
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame


@pytest.mark.gpu
@pytest.mark.asyncio
async def test_matched_depth_inspection_and_layout(tmp_path):
    media = Media()
    encoder = CodecWorker(Config(width=320, height=240), encode=True)
    values = np.full((240, 320), 0.5, np.float32)
    values[:40, :40] = 0
    header, payload = encoder.encode(
        Frame(
            VideoHeader(0, time.time_ns(), 320, 240),
            np.full((240, 320, 3), 128, np.uint8),
            depth=values,
        )
    )
    encoder.close()
    app = web.Application()
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    app.router.add_static("/static", static)

    async def offer(request):
        value = await request.json()
        return web.json_response(await media.offer("camera", value["sdp"], value["type"]))

    app.router.add_post("/offer", offer)

    async def index(request):
        return web.Response(
            content_type="text/html",
            text="""
        <link rel="stylesheet" href="/static/style.css">
        <div class="video-tile" style="width:640px;max-width:100%">
        <div class="depth-stage"><video autoplay muted playsinline></video></div>
        <div class="video-caption"></div></div>
        <script type="module">
        import {depthView} from '/static/depth.js';
        const peer = new RTCPeerConnection({iceServers:[]});
        const video = document.querySelector('video');
        window.depth = depthView(peer, video, document.querySelector('.depth-stage'),
          document.querySelector('.video-caption'),
          {name:'Camera',depth:true,depth_source:'measured'});
        peer.ontrack = ({track}) => video.srcObject = new MediaStream([track]);
        const receiver=peer.addTransceiver('video',{direction:'recvonly'});
        receiver.setCodecPreferences(RTCRtpReceiver.getCapabilities('video').codecs.filter(c=>c.mimeType==='video/H264'));
        await peer.setLocalDescription(await peer.createOffer());
        const answer=await fetch('/offer',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({sdp:peer.localDescription.sdp,type:'offer'})}).then(r=>r.json());
        await peer.setRemoteDescription(answer);
        </script>""",
        )

    app.router.add_get("/", index)

    async def publish():
        while True:
            await media.put("camera", asdict(replace(header, captured_ns=time.time_ns())), payload)
            await asyncio.sleep(1 / 30)

    producer = asyncio.create_task(publish())
    try:
        async with TestServer(app) as server, async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(str(server.make_url("/")))
                await page.get_by_label("Depth display", exact=True).select_option("overlay")
                await expect(page.locator(".depth-reading")).to_contain_text(
                    "Measured depth", timeout=20000
                )
                canvas = page.locator("canvas")
                await canvas.click(position={"x": 320, "y": 240})
                await expect(page.locator(".depth-reading")).to_contain_text("500.0 mm")
                await page.screenshot(path=str(tmp_path / "depth-overlay.png"))
                await page.get_by_label("Depth display", exact=True).select_option("side")
                await expect(page.locator(".depth-reading")).to_contain_text("500.0 mm")
                left, right = (
                    await page.locator("video").bounding_box(),
                    await canvas.bounding_box(),
                )
                assert right["x"] == pytest.approx(left["x"] + left["width"], abs=1)
                await page.screenshot(path=str(tmp_path / "depth-side.png"))
                await page.set_viewport_size({"width": 390, "height": 844})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await page.get_by_label("Depth display", exact=True).select_option("color")
                await expect(canvas).to_be_hidden()
                assert not errors
            finally:
                await browser.close()
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
        await media.clear()
