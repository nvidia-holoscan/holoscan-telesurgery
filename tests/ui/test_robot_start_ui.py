# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
async def test_patient_start_confirmation_and_node_layout(tmp_path):
    robot = {
        "id": "node:mira",
        "node": "node",
        "name": "MIRA",
        "kind": "mira",
        "status": "disconnected",
        "connection_enabled": False,
        "node_online": True,
        "stale": True,
        "controls": {"groups": {"left": 5, "right": 5}},
        "controller": {"status": "stopped", "error": ""},
    }
    state = {
        "role": "patient",
        "sdk": "5",
        "surgeons": [],
        "robots": [robot],
        "nodes": [{"id": "node", "name": "MIRA node", "status": "online"}],
        "cameras": [
            {
                "id": "node:camera",
                "node": "node",
                "name": "MIRA camera",
                "kind": "USB",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "status": "stopped",
                "codec": "h264",
            }
        ],
    }
    calls, errors = [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            calls.append(json.loads(request.request.post_data))
            connected = calls[-1]["action"] != "robot.disconnect"
            robot["connection_enabled"] = connected
            robot["status"] = "starting" if connected else "disconnected"
            robot["controller"]["status"] = "running"
            await request.fulfill(json={"result": True})
        elif path.startswith("api/robots/"):
            await request.fulfill(
                json={"text": "Loading MIRA controller", "updated_seconds_ago": 1}
            )
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1744, "height": 980})
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/#node/node")
            start = page.locator("#equipment-rows").get_by_role(
                "button", name="Connect", exact=True
            )
            await expect(start).to_be_enabled()
            await expect(page.locator("#equipment-rows tr")).to_have_count(2)
            await expect(page.locator("#views-panel")).to_be_hidden()
            await start.click()
            submit = page.locator("#confirm-robot-start")
            await expect(submit).to_be_disabled()
            await page.locator("#cancel-robot-start").click()
            assert not calls
            await start.click()
            await page.locator("#robot-operator-ready").check()
            await submit.click()
            assert calls == [
                {"action": "robot.start", "params": {"id": "node:mira", "confirmed": True}}
            ]
            disconnect = page.locator("#equipment-rows").get_by_role(
                "button", name="Disconnect", exact=True
            )
            await expect(disconnect).to_be_enabled()
            await expect(page.locator("#equipment-rows")).to_contain_text("Connecting")
            robot.update(status="online", stale=False)
            await expect(page.locator("#equipment-rows")).to_contain_text("Available")
            robot.update(status="offline", stale=True, error="Controller connection failed")
            await expect(page.locator("#equipment-rows")).to_contain_text("Control error")
            robot["error"] = ""
            await disconnect.click()
            assert calls[-1]["action"] == "robot.disconnect"
            await expect(page.locator("#equipment-rows")).to_contain_text("Disconnected")
            await start.click()
            assert calls[-1]["action"] == "robot.connect"
            await expect(page.locator("#robot-start-dialog")).to_be_hidden()
            await (
                page.locator("#equipment-rows")
                .get_by_role("button", name="Logs", exact=True)
                .click()
            )
            await expect(page.locator("#log-output")).to_have_text("Loading MIRA controller")
            await page.keyboard.press("Escape")
            for width in (1744, 1100, 850, 390):
                await page.set_viewport_size({"width": width, "height": 980})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await expect(page.locator("#equipment-panel")).to_be_visible()
                await page.screenshot(
                    path=str(tmp_path / f"robot-start-{width}.png"), full_page=True
                )
            assert not errors
        finally:
            await browser.close()
