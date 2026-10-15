# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Device preferences survive reloads independently of the robot control lease."""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import MiraSimulation

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("device", ["haply", "0"])
@pytest.mark.parametrize("acquired", [False, True])
@pytest.mark.parametrize("hard_reload", [False, True])
async def test_input_preference_survives_reload_and_delayed_discovery(
    device, acquired, hard_reload,
):
    robot = {
        "id": "node:mira", "name": "MIRA", "kind": "mira-sim", "simulation": True,
        "status": "online",
        "controls": controls(MiraSimulation({"uri": "unused"}), {"motion_enabled": True}),
        "state": {"sequence": 1},
    }
    state = {
        "role": "surgeon", "sdk": "5", "patient": "patient-one:7447", "selected": [],
        "haply_available": True,
        "session": {"id": "operator", "name": "Operator", "status": "approved",
                    "robot": True, "robots": [robot], "cameras": []},
    }
    calls, errors = [], []

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            body = request.request.post_data_json
            calls.append(body)
            if body["action"] == "haply.read":
                result = {"paused": True, "request": None}
            else:
                robot["state"]["sequence"] += 1
                result = robot["state"]
            await request.fulfill(json={"result": result})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script("""
                document.hasFocus = () => true;
                window.pads = [];
                window.pad = {id:'Xbox controller', index:0, mapping:'standard', connected:true,
                    axes:[0,0,0,0], buttons:Array.from({length:17},()=>({pressed:false,value:0}))};
                navigator.getGamepads = () => window.pads;
            """)
            await page.route("http://localhost:8777/**", route)
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto("http://localhost:8777/")
            await page.evaluate("pads = [pad]")
            selector = page.get_by_label("MIRA input", exact=True)
            await selector.select_option(device)
            if acquired:
                await page.get_by_role("button", name="Acquire control", exact=True).click()
            state["haply_available"] = False
            if hard_reload:
                cdp = await page.context.new_cdp_session(page)
                async with page.expect_event("load"):
                    await cdp.send("Page.reload", {"ignoreCache": True})
                await cdp.detach()
            else:
                await page.reload()
            await expect(selector).to_have_value("keyboard")
            # Startup discovery can lag behind rendering the robot card. A different
            # pad at the same index must never inherit the saved device's selection.
            await page.evaluate("pads = [{...pad, id:'Different controller'}]")
            await expect(selector.locator('option[value="0"]')).to_have_count(1)
            await expect(selector).to_have_value("keyboard")
            state["haply_available"] = True
            await page.evaluate("pads = [pad]")
            await expect(selector).to_have_value(device)
            await page.wait_for_timeout(150)
            assert sum(c["action"] == "robot.acquire" for c in calls) == int(acquired)
            assert not any(c["action"] == "robot.move" for c in calls)
            reads = [c for c in calls if c["action"] == "haply.read"]
            if device == "haply":
                assert reads and not reads[-1]["params"]["enabled"]

            # An explicit keyboard choice replaces the preference, including while
            # the previous device is still waiting to be discovered after reload.
            state["haply_available"] = False
            await page.reload()
            await expect(selector).to_have_value("keyboard")
            await selector.select_option("keyboard")
            state["haply_available"] = True
            await page.evaluate("pads = [pad]")
            await expect(selector.locator('option[value="haply"]')).to_have_count(1)
            await expect(selector).to_have_value("keyboard")
            await page.reload()
            await page.evaluate("pads = [pad]")
            await expect(selector.locator('option[value="haply"]')).to_have_count(1)
            await expect(selector).to_have_value("keyboard")

            # Preferences belong to a robot on a particular patient connection.
            await selector.select_option(device)
            state["patient"] = "patient-two:7447"
            await page.reload()
            await page.evaluate("pads = [pad]")
            await expect(selector.locator('option[value="0"]')).to_have_count(1)
            await expect(selector).to_have_value("keyboard")
            assert not errors
        finally:
            await browser.close()
