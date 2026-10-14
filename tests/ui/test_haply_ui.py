# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Headless checks for browser Haply selection and cancellation of delayed input."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import (
    FrankaSimulation,
    MiraSimulation,
    VersiusSimulation,
)

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["mira", "franka", "versius"])
async def test_haply_browser_selection_focus_stop_and_delayed_reply(kind):
    name = {"mira": "MIRA", "franka": "Franka", "versius": "Versius left"}[kind]
    adapter = {"mira": MiraSimulation, "franka": FrankaSimulation, "versius": VersiusSimulation}[
        kind
    ]
    robot = {
        "id": kind,
        "name": name,
        "kind": kind + "-sim",
        "simulation": True,
        "status": "online",
        "controls": controls(adapter({"uri": "unused"}), {"motion_enabled": True}),
        "state": {"sequence": 1, "grippers": {"left": 0, "right": 1}},
    }
    if kind == "franka":
        robot["controls"]["grippers"] = []
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "native_views": {},
        "native_controller": {"status": "closed"},
        "session": {
            "id": "operator",
            "name": "Operator",
            "status": "approved",
            "robot": True,
            "robots": [robot],
            "cameras": [],
        },
    }
    calls, errors = [], []
    result = {"request": None, "paused": True, "arm": "left", "error": "Calibrate the Inverse3."}
    gate = None

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            body = request.request.post_data_json
            calls.append(body)
            if body["action"] == "haply.read":
                reply = dict(result)
                if gate is not None:
                    await gate.wait()
                await request.fulfill(json={"result": reply})
            else:
                robot["state"]["sequence"] += 1
                await request.fulfill(json={"result": robot["state"]})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(bypass_csp=True)
            await context.add_init_script("""
                window.focused = true;
                document.hasFocus = () => window.focused;
                window.pads = [];
                navigator.getGamepads = () => window.pads;
            """)
            await context.route("http://localhost:8777/**", route)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto("http://localhost:8777/")
            selector = page.get_by_label(f"{name} input", exact=True)
            await expect(selector.locator('option[value="haply"]')).to_have_count(0)
            assert not any(c["action"] == "haply.read" for c in calls)
            state["haply_available"] = True
            await expect(selector.locator('option[value="haply"]')).to_have_count(1)
            await selector.select_option("haply")
            await expect(page.locator(".haply-controls")).to_be_visible()
            await expect(page.locator(".gamepad-controls:not(.haply-controls)")).to_be_hidden()
            await expect(page.get_by_label(f"{name} arm speed", exact=True)).to_be_visible()
            if kind == "mira":
                await expect(page.get_by_label("MIRA roll speed", exact=True)).to_be_visible()
            assert not any(c["action"] == "robot.move" for c in calls)
            await expect(page.locator(".haply-controls")).to_contain_text(
                "Tap single-dot button · Start / stop"
            )
            if kind == "mira":
                await expect(page.locator(".haply-controls")).to_contain_text(
                    "Tap two-dot button · Switch"
                )
                await expect(page.locator(".haply-controls")).not_to_contain_text("A + C")
                await expect(page.locator(".haply-controls")).to_contain_text(
                    "Hold single-dot button · Close gripper"
                )
                await expect(
                    page.locator(".haply-controls .gripper-controls button:visible")
                ).to_have_count(0)
                await expect(
                    page.locator(".haply-controls .gripper-feedback meter:visible")
                ).to_have_count(2)
            await expect(page.locator(".haply-controls .input-discovery")).to_have_text(
                "Calibrate the Inverse3."
            )
            await expect(page.locator(".haply-controls .motion-section").nth(1)).to_contain_text(
                "Twist pen · Roll tool"
            )
            await expect(page.locator(".haply-controls .motion-section").nth(0)).to_contain_text(
                "Tilt pen up / down · Angle tool" if kind == "mira" else "Tilt pen · Angle tool"
            )
            # Gamepad discovery refresh must preserve Haply selection.
            await page.evaluate("""window.pads = [{
                id:'Xbox',index:0,connected:true,mapping:'standard',
                axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false,value:0}))}]""")
            await expect(selector.locator("option")).to_have_count(3)
            await expect(selector).to_have_value("haply")
            # Input selection is a local preference; every device remains idle
            # until the surgeon explicitly acquires control.
            await selector.select_option("0")
            await expect(page.locator(".gamepad-controls:not(.haply-controls)")).to_be_visible()
            await page.evaluate("pads[0].buttons[4].pressed=true;pads[0].axes[0]=1")
            await page.wait_for_timeout(150)
            await selector.select_option("keyboard")
            await expect(page.locator(".keyboard-controls")).to_be_visible()
            await page.keyboard.press("q")
            await selector.select_option("haply")
            await page.wait_for_timeout(150)
            assert not any(c["action"].startswith("robot.") for c in calls)
            reads = [c for c in calls if c["action"] == "haply.read"]
            assert reads and all(not c["params"]["enabled"] for c in reads)
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await expect(page.locator(".haply-controls .input-discovery")).to_have_text(
                "Calibrate the Inverse3."
            )
            motion = (
                ["cartesian", {"left": [0.1, 0, 0, 0, 0], "right": [0] * 5}]
                if kind == "mira"
                else ["jog", {"translation": [0.1, 0, 0], "rotation": [0, 0, 0]}]
            )
            result.update(request=motion, paused=False, error="")
            await expect(page.locator(".haply-controls [role=status]")).to_have_text(
                "Active · Left arm" if kind == "mira" else "Active"
            )
            for _ in range(40):
                if any(c["action"] == "robot.move" for c in calls):
                    break
                await asyncio.sleep(0.025)
            assert any(c["action"] == "robot.move" for c in calls)
            assert next(c for c in calls if c["action"] == "haply.read")["params"]["speeds"] == {
                "arm": 20,
                "roll": 50,
                "grip": 40,
            }
            # Escape during an outstanding read must discard that response.
            gate = asyncio.Event()
            before = sum(c["action"] == "haply.read" for c in calls)
            while sum(c["action"] == "haply.read" for c in calls) == before:
                await asyncio.sleep(0.025)
            result.update(request=None, paused=True)
            await page.keyboard.press("Escape")
            sent = sum(c["action"] == "robot.move" for c in calls)
            gate.set()
            gate = None
            await asyncio.sleep(0.15)
            assert sum(c["action"] == "robot.move" for c in calls) == sent
            assert any(c["action"] == "robot.hold" for c in calls)
            # A hidden/unfocused browser never forwards device motion.
            await page.evaluate("window.focused = false; window.dispatchEvent(new Event('blur'))")
            result.update(request=motion, paused=False)
            await asyncio.sleep(0.2)
            assert sum(c["action"] == "robot.move" for c in calls) == sent
            assert any(c["action"] == "haply.read" and not c["params"]["enabled"] for c in calls)
            await page.evaluate("window.focused = true")
            result.update(request=None, paused=True)
            if kind == "mira":
                async with page.expect_request(
                    lambda r: (
                        r.url.endswith("/api/action")
                        and r.post_data_json.get("action") == "robot.move"
                        and r.post_data_json["params"].get("mode") == "reset"
                    )
                ):
                    await page.get_by_role("button", name="Reset scene", exact=True).click()
            stop_button = page.get_by_role("button", name="Stop", exact=True)
            assert await stop_button.locator("svg").count() == 1
            assert await stop_button.locator("kbd").count() == 0
            state["haply_available"] = False
            await expect(selector.locator('option[value="haply"]')).to_have_count(0)
            await expect(selector).to_have_value("keyboard")
            await expect(page.locator(".haply-controls")).to_be_hidden()
            assert errors == []
        finally:
            if gate:
                gate.set()
            await browser.close()
