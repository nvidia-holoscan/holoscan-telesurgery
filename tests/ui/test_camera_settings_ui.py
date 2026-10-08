# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stream setup keeps resolution, FPS and format combinations valid."""

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["USB", "HSB"])
@pytest.mark.parametrize("codec", ["h264", "h265", "nvjpeg", "raw-bgr8"])
async def test_stream_options_and_patient_owned_encoder_settings(kind, codec, tmp_path):
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
        "codecs": ["raw-bgr8", "h264", "h265", "nvjpeg"],
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
            await page.get_by_label("Quality (QP)", exact=True).fill("18")
            await page.get_by_label("Encoder speed", exact=True).select_option("P3")
            await page.get_by_label("Stream codec", exact=True).select_option(codec)
            if codec == "nvjpeg":
                await expect(page.get_by_label("Quality (QP)", exact=True)).not_to_be_visible()
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
            if codec != "h264":
                await expect(page.locator("#stream-viewing")).to_contain_text("View in Holoviz")
            await page.screenshot(path=str(tmp_path / f"{kind}-settings.png"))
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.screenshot(
                path=str(tmp_path / f"{kind}-settings-mobile.png"), full_page=True
            )
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.get_by_role("button", name="Start stream", exact=True).click()
            await expect(page.get_by_role("dialog", name="Start stream")).not_to_be_visible()
            assert actions[0] == {
                "action": "camera.start",
                "params": {
                    "id": camera["id"],
                    "settings": {
                        "width": 3840,
                        "height": 2160,
                        "fps": 30 if kind == "USB" else 60,
                        "pixel_format": "MJPG" if kind == "USB" else "",
                        "codec": codec,
                        **(
                            {}
                            if codec == "raw-bgr8"
                            else {"jpeg_quality": 92}
                            if codec == "nvjpeg"
                            else {"qp": 18, "encoder_preset": "P3"}
                        ),
                    },
                },
            }
            await page.get_by_role("button", name="Stop", exact=True).click()
            await page.get_by_role("button", name="Stream settings", exact=True).click()
            await expect(page.get_by_label("Resolution", exact=True)).to_have_value("3840x2160")
            assert not errors
        finally:
            await browser.close()
