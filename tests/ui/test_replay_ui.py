# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay visibility and Stop use the same dashboard ownership and input gates."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import FrankaSimulation, MiraSimulation

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["escape", "complete", "blur", "hidden", "error"])
@pytest.mark.parametrize(
    "environment,name,adapter,width",
    [
        ("franka", "Franka", FrankaSimulation, 1280),
        ("mira", "MIRA", MiraSimulation, 1280),
        ("mira", "MIRA", MiraSimulation, 360),
    ],
)
async def test_replay_requires_matching_recording_and_ownership_and_escape_discards_reply(
    environment, name, adapter, width, ending, tmp_path
):
    robot = {
        "id": f"node:{environment}",
        "name": name,
        "kind": f"{environment}-sim",
        "simulation": True,
        "status": "online",
        "state": {"sequence": 1},
        "controls": controls(adapter({"uri": "unused"}), {"motion_enabled": True}),
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "native_views": {},
        "native_controller": {"status": "closed"},
        "replays": [],
        "session": {
            "id": "X",
            "name": "X",
            "status": "approved",
            "robot": True,
            "robots": [robot],
            "cameras": [],
        },
    }
    calls, errors = [], []
    gate, reading = asyncio.Event(), asyncio.Event()
    move_gate = asyncio.Event()

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            body = request.request.post_data_json
            calls.append(body)
            method = body["action"]
            if method == "replay.read":
                reading.set()
                await gate.wait()
                if ending == "error":
                    await request.fulfill(
                        status=400, json={"error": "Measured feedback unavailable"}
                    )
                    return
                result = {
                    "request": None
                    if ending == "complete"
                    else ["jog", {"translation": [1, 0, 0], "rotation": [0, 0, 0]}],
                    "speed_deg_s": 3,
                    "elapsed": 0.1,
                    "done": ending == "complete",
                    "feedback_paced": True,
                }
            elif method.startswith("replay."):
                result = True
            else:
                if method == "robot.move" and ending == "blur":
                    await move_gate.wait()
                    await request.fulfill(status=400, json={"error": "Replay stopped"})
                    return
                if method == "robot.acquire":
                    robot.update(owner="X", owner_id="X")
                if method == "robot.release":
                    robot.update(owner=None, owner_id=None)
                robot["state"]["sequence"] += 1
                result = robot["state"]
            await request.fulfill(json={"result": result})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                bypass_csp=True, viewport={"width": width, "height": 900}
            )
            await context.add_init_script(
                "document.hasFocus = () => true; navigator.getGamepads = () => [];"
            )
            await context.route("http://localhost:8777/**", route)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto("http://localhost:8777/")
            control = page.get_by_role("button", name="Replay inputs", exact=True)
            await expect(control).to_be_hidden()
            state["replays"] = [
                {
                    "id": f"{environment}/keyboard",
                    "environment": environment,
                    "device": "keyboard",
                    "task": "Scan",
                    "streams": [environment],
                }
            ]
            await page.wait_for_timeout(1100)
            await expect(control).to_be_hidden()
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await expect(control).to_be_visible()
            await control.click()
            await asyncio.wait_for(reading.wait(), 3)
            selector = page.get_by_label(f"{name} input", exact=True)
            await expect(selector).to_be_disabled()
            toolbar = await page.locator(".robot-toolbar").bounding_box()
            message = await page.locator(".replay-status").bounding_box()
            assert message["y"] >= toolbar["y"] + toolbar["height"]
            assert (await selector.bounding_box())["width"] >= 120
            assert await page.locator(".robot-toolbar").evaluate(
                "e => e.scrollWidth <= e.clientWidth"
            )
            await page.locator("#robots-panel").screenshot(path=str(tmp_path / "replay-layout.png"))
            await page.wait_for_timeout(250)
            assert any(c["action"] == "replay.heartbeat" for c in calls)
            if ending == "escape":
                await page.keyboard.press("Escape")
            elif ending == "blur":
                await page.evaluate(
                    "document.hasFocus = () => false; window.dispatchEvent(new Event('blur'))"
                )
                gate.set()
                await page.wait_for_timeout(250)
                assert any(c["action"] == "robot.move" for c in calls)
                assert not any(c["action"] == "replay.cancel" for c in calls)
                assert not any(c["action"] == "robot.hold" for c in calls)
                await expect(selector).to_be_disabled()
                await page.evaluate("document.hasFocus = () => true")
                await page.keyboard.press("Escape")
                move_gate.set()
            elif ending == "hidden":
                await page.evaluate(
                    "Object.defineProperty(document, 'hidden', {value: true, configurable: true});"
                    "document.dispatchEvent(new Event('visibilitychange'))"
                )
            gate.set()
            await page.wait_for_timeout(250)
            assert any(c["action"] == "replay.cancel" for c in calls) == (ending != "complete")
            if ending == "complete":
                await expect(page.locator(".replay-status")).to_have_text("Replay complete")
            else:
                reason = (
                    "dashboard hidden"
                    if ending == "hidden"
                    else "Measured feedback unavailable"
                    if ending == "error"
                    else "Escape pressed"
                )
                await expect(page.locator(".replay-status")).to_have_text(
                    f"Replay stopped · {reason}"
                )
            if ending != "blur":
                assert not any(c["action"] == "robot.move" for c in calls)
            else:
                stopped = sum(c["action"] == "robot.move" for c in calls)
                await page.wait_for_timeout(150)
                assert sum(c["action"] == "robot.move" for c in calls) == stopped
                await expect(page.locator("#notice")).to_be_hidden()
            await expect(selector).to_be_enabled()
            await page.get_by_role("button", name="Release control", exact=True).click()
            await expect(control).to_be_hidden()
            assert not errors
        finally:
            gate.set()
            move_gate.set()
            await browser.close()
