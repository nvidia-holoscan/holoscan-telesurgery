# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stream setup keeps resolution, FPS and format combinations valid."""

import asyncio
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["USB", "HSB"])
@pytest.mark.parametrize("codec", ["h264", "h265", "nvjpeg", "raw-bgr8", "surgical-tokenizer"])
async def test_stream_options_and_patient_owned_encoder_settings(kind, codec):
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    usb_modes = [
        {"width": 640, "height": 480, "fps": [30], "pixel_format": "YUYV"},
        {"width": 1920, "height": 1080, "fps": [30], "pixel_format": "YUYV"},
        {"width": 1920, "height": 1080, "fps": [60, 30], "pixel_format": "MJPG"},
        {"width": 3840, "height": 2160, "fps": [30], "pixel_format": "MJPG"},
    ]
    camera = {
        "id": "host:camera",
        "node": "host",
        "name": "Logitech BRIO · Color" if kind == "USB" else "IMX274",
        "kind": kind,
        "width": 640 if kind == "USB" else 1920,
        "height": 480 if kind == "USB" else 1080,
        "fps": 30 if kind == "USB" else 60,
        "pixel_format": "YUYV" if kind == "USB" else "",
        "status": "stopped",
        "codecs": ["raw-bgr8", "h264", "h265", "nvjpeg", "surgical-tokenizer"],
        "modes": usb_modes
        if kind == "USB"
        else [
            {"width": 1920, "height": 1080, "fps": [60]},
            {"width": 3840, "height": 2160, "fps": [60]},
        ],
    }
    state = {
        "role": "patient",
        "sdk": "5",
        "nodes": [{"id": "host", "name": "Workstation", "status": "online"}],
        "cameras": [camera],
        "robots": [],
        "surgeons": [],
        "endpoint_port": 7447,
    }
    actions, errors = [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            actions.append(body)
            if body["action"] == "camera.start":
                camera.update(body["params"]["settings"])
                camera["status"] = "live"
            else:
                camera["status"] = "stopped"
            await request.fulfill(json={"result": True})
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 960})
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/#node/host")
            await page.get_by_role("button", name="Stream settings", exact=True).click()
            await expect(page.get_by_role("dialog", name="Start stream")).to_be_visible()
            await expect(page.get_by_label("Stream codec", exact=True)).to_have_value("h264")
            await expect(page.get_by_text("Encoder settings", exact=True)).to_be_visible()
            if kind == "USB":
                await expect(page.get_by_label("Capture format", exact=True)).to_have_value("YUYV")
            assert not actions
            if kind == "USB":
                await page.get_by_label("Resolution", exact=True).select_option("1920x1080")
                await page.get_by_label("Frame rate", exact=True).select_option("60")
                await expect(page.get_by_label("Capture format", exact=True)).to_have_value("MJPG")
                await expect(page.get_by_label("Capture format", exact=True)).to_be_disabled()
            await page.get_by_label("Resolution", exact=True).select_option("3840x2160")
            await expect(page.get_by_label("Frame rate", exact=True)).to_have_value(
                "30" if kind == "USB" else "60"
            )
            await page.get_by_label("Stream codec", exact=True).select_option("h264")
            await page.get_by_text("Encoder settings", exact=True).click()
            await page.get_by_label("Average bitrate (Mbps)", exact=True).fill("12.5")
            await page.get_by_label("Encoder speed", exact=True).select_option("P3")
            if codec == "surgical-tokenizer":
                await expect(
                    page.locator('#stream-codec option[value="surgical-tokenizer"]')
                ).to_have_attribute("disabled", "")
                await page.get_by_label("Resolution", exact=True).select_option("1920x1080")
                if kind == "USB":
                    await page.get_by_label("Frame rate", exact=True).select_option("30")
            await page.get_by_label("Stream codec", exact=True).select_option(codec)
            if codec == "surgical-tokenizer":
                await expect(page.get_by_text("Encoder settings", exact=True)).not_to_be_visible()
                await expect(page.locator("#stream-viewing")).to_contain_text("browser or Holoviz")
            if codec == "nvjpeg":
                await expect(
                    page.get_by_label("Average bitrate (Mbps)", exact=True)
                ).not_to_be_visible()
                await page.get_by_label("JPEG quality", exact=True).fill("92")
            if codec == "raw-bgr8":
                await expect(page.get_by_text("Encoder settings", exact=True)).not_to_be_visible()
                await expect(page.locator("#stream-viewing")).to_contain_text(
                    "5.97 Gbit/s" if kind == "USB" else "11.94 Gbit/s"
                )
                if kind == "USB":
                    await expect(page.locator("#stream-viewing")).to_contain_text(
                        "Camera capture is still JPEG-compressed"
                    )
            if codec not in {"h264", "surgical-tokenizer"}:
                await expect(page.locator("#stream-viewing")).to_contain_text("View in Holoviz")
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.get_by_role("button", name="Start stream", exact=True).click()
            await expect(page.get_by_role("dialog", name="Start stream")).not_to_be_visible()
            assert actions[0] == {
                "action": "camera.start",
                "params": {
                    "id": camera["id"],
                    "settings": {
                        "width": 1920 if codec == "surgical-tokenizer" else 3840,
                        "height": 1080 if codec == "surgical-tokenizer" else 2160,
                        "fps": 30 if kind == "USB" else 60,
                        "pixel_format": "MJPG" if kind == "USB" else "",
                        "codec": codec,
                        **(
                            {}
                            if codec in {"raw-bgr8", "surgical-tokenizer"}
                            else {"jpeg_quality": 92}
                            if codec == "nvjpeg"
                            else {
                                "rate_control": "cbr",
                                "bitrate_mbps": 12.5,
                                "encoder_preset": "P3",
                                "encoder_extra": "",
                            }
                        ),
                    },
                },
            }
            if codec == "surgical-tokenizer":
                # Closing the form precedes the status refresh. Reopen settings
                # only after the dashboard has observed that capture is live.
                await expect(page.get_by_role("button", name="Stop", exact=True)).to_be_visible()
                await page.get_by_role("button", name="Stream settings", exact=True).click()
                await expect(page.get_by_label("Resolution", exact=True)).to_be_disabled()
                await expect(page.get_by_label("Frame rate", exact=True)).to_be_disabled()
                await page.get_by_label("Stream codec", exact=True).select_option("h264")
                await page.get_by_role("button", name="Apply encoding", exact=True).click()
                assert actions[-1]["action"] == "camera.start"
                assert actions[-1]["params"]["settings"]["codec"] == "h264"
                assert camera["status"] == "live"
            await page.get_by_role("button", name="Stop", exact=True).click()
            await page.get_by_role("button", name="Stream settings", exact=True).click()
            await expect(page.get_by_label("Resolution", exact=True)).to_have_value(
                "1920x1080" if codec == "surgical-tokenizer" else "3840x2160"
            )
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_rate_control_automatic_bitrate_and_advanced_encoder_settings():
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    camera = {
        "id": "host:camera",
        "node": "host",
        "name": "IMX274",
        "kind": "HSB",
        "width": 1920,
        "height": 1080,
        "fps": 60,
        "pixel_format": "",
        "status": "stopped",
        "codecs": ["h264", "h265", "nvjpeg"],
        "modes": [
            {"width": 1280, "height": 720, "fps": [60]},
            {"width": 1920, "height": 1080, "fps": [60]},
            {"width": 3840, "height": 2160, "fps": [60]},
        ],
    }
    state = {
        "role": "patient",
        "sdk": "5",
        "nodes": [{"id": "host", "name": "Workstation", "status": "online"}],
        "cameras": [camera],
        "robots": [],
        "surgeons": [],
        "endpoint_port": 7447,
    }
    actions, errors, served = [], [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
            served.append(len(actions))
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            actions.append(body)
            if body["action"] == "camera.start":
                camera.update(body["params"]["settings"])
                camera["status"] = "live"
            else:
                camera["status"] = "stopped"
            await request.fulfill(json={"result": True})
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 960})
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def refreshed():
                # The dashboard has drawn a status fetched after the last action; until
                # then the Stream settings button still holds the earlier camera.
                async with asyncio.timeout(10):
                    while not served or served[-1] < len(actions):
                        await asyncio.sleep(0.02)
                await page.evaluate("() => new Promise((resolve) => setTimeout(resolve, 0))")

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/#node/host")
            await page.get_by_role("button", name="Stream settings", exact=True).click()
            await page.get_by_text("Encoder settings", exact=True).click()
            rate = page.get_by_label("Rate control", exact=True)
            bitrate = page.locator("#stream-bitrate")
            max_bitrate = page.get_by_label("Max bitrate (Mbps)", exact=True)
            quality = page.get_by_label("QP (lower is sharper)", exact=True)
            await expect(rate).to_have_value("cbr")
            await expect(max_bitrate).not_to_be_visible()
            # With an empty bitrate, CBR uses the resolution default.
            await expect(bitrate).to_have_value("")
            await expect(bitrate).to_have_attribute("placeholder", "Automatic · 10")
            await page.get_by_label("Resolution", exact=True).select_option("3840x2160")
            await expect(bitrate).to_have_attribute("placeholder", "Automatic · 30")
            await page.get_by_label("Resolution", exact=True).select_option("1280x720")
            await expect(bitrate).to_have_attribute("placeholder", "Automatic · 5")
            await expect(quality).not_to_be_visible()
            await expect(page.locator("#stream-extra")).not_to_be_visible()
            await page.get_by_role("button", name="Start stream", exact=True).click()
            await expect(page.get_by_role("dialog", name="Start stream")).not_to_be_visible()
            settings = actions[-1]["params"]["settings"]
            assert settings["rate_control"] == "cbr" and settings["bitrate_mbps"] == 0
            assert settings["encoder_extra"] == "" and "qp" not in settings

            # Fixed quality replaces the bitrate with a QP; advanced settings are free text.
            await refreshed()
            await expect(page.get_by_role("button", name="Stop", exact=True)).to_be_visible()
            await page.get_by_role("button", name="Stream settings", exact=True).click()
            await page.get_by_text("Encoder settings", exact=True).click()
            await rate.select_option("cqp")
            await expect(bitrate).not_to_be_visible()
            await quality.fill("28")
            await page.get_by_text("Advanced", exact=True).click()
            await page.locator("#stream-extra").fill("aq=8\ngop_seconds=5")
            await page.get_by_role("button", name="Apply encoding", exact=True).click()
            await expect(page.get_by_role("dialog", name="Change encoding")).not_to_be_visible()
            settings = actions[-1]["params"]["settings"]
            assert settings["rate_control"] == "cqp" and settings["qp"] == 28
            assert settings["encoder_extra"] == "aq=8\ngop_seconds=5"
            assert "bitrate_mbps" not in settings

            # The dialog reopens with the stream's settings, advanced section included.
            await refreshed()
            await page.get_by_role("button", name="Stream settings", exact=True).click()
            await page.get_by_text("Encoder settings", exact=True).click()
            await expect(rate).to_have_value("cqp")
            await expect(quality).to_have_value("28")
            await expect(page.locator("#stream-extra")).to_have_value("aq=8\ngop_seconds=5")
            await rate.select_option("vbr")
            await expect(quality).not_to_be_visible()
            await bitrate.fill("8")
            await expect(page.get_by_label("Average bitrate (Mbps)", exact=True)).to_be_visible()
            await max_bitrate.fill("13.5")
            await page.get_by_role("button", name="Apply encoding", exact=True).click()
            await expect(page.get_by_role("dialog", name="Change encoding")).not_to_be_visible()
            settings = actions[-1]["params"]["settings"]
            assert settings["rate_control"] == "vbr" and settings["bitrate_mbps"] == 8
            assert settings["max_bitrate_mbps"] == 13.5

            await refreshed()
            await page.get_by_role("button", name="Stream settings", exact=True).click()
            await page.get_by_text("Encoder settings", exact=True).click()
            await expect(max_bitrate).to_have_value("13.5")
            await rate.select_option("cbr")
            await expect(page.get_by_label("Average bitrate (Mbps)", exact=True)).to_be_visible()
            await expect(max_bitrate).not_to_be_visible()
            await bitrate.fill("10")
            await page.get_by_role("button", name="Apply encoding", exact=True).click()
            await expect(page.get_by_role("dialog", name="Change encoding")).not_to_be_visible()
            settings = actions[-1]["params"]["settings"]
            assert settings["rate_control"] == "cbr" and settings["bitrate_mbps"] == 10
            assert "max_bitrate_mbps" not in settings
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["patient", "surgeon"])
async def test_encoding_warning_keeps_live_view_and_controls(role):
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    camera = {
        "id": "host:camera",
        "node": "host",
        "name": "Camera",
        "kind": "USB",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "codec": "h264",
        "status": "live",
        "codecs": ["h264", "surgical-tokenizer"],
    }
    state = {
        "role": role,
        "sdk": "5",
        "selected": [camera["id"]],
        "nodes": [{"id": "host", "name": "Workstation", "status": "online"}],
        "cameras": [camera],
        "robots": [],
        "surgeons": [],
        "session": {"id": "operator", "status": "approved", "cameras": [camera]},
    }

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        elif path == "api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script("""
                window.RTCPeerConnection=class {
                    constructor(){this.iceGatheringState='complete'}
                    addTransceiver(){return {setCodecPreferences(){}}}
                    createDataChannel(){return {readyState:'connecting',send(){}}}
                    async createOffer(){return {type:'offer',sdp:'test'}}
                    async setLocalDescription(d){this.localDescription=d}
                    async setRemoteDescription(){} close(){} async getStats(){return new Map()}
                };
            """)
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/" + ("#node/host" if role == "patient" else ""))
            if role == "patient":
                await page.get_by_role("button", name="Preview", exact=True).click()
            await expect(page.locator(".video-tile")).to_have_count(1)
            tile = await page.locator(".video-tile").element_handle()
            camera["encoding_error"] = "Could not prepare surgical-tokenizer; continuing h264"
            await expect(page.locator(".encoding-warning")).to_contain_text("continuing h264")
            assert await tile.evaluate("tile => tile.isConnected")
            if role == "patient":
                await expect(page.get_by_role("button", name="Stop", exact=True)).to_be_enabled()
                await page.get_by_role("button", name="Stream settings", exact=True).click()
                await expect(
                    page.get_by_role("button", name="Apply encoding", exact=True)
                ).to_be_visible()
            camera["encoding_error"] = ""
            await expect(page.locator(".encoding-warning")).to_have_count(0)
        finally:
            await browser.close()
