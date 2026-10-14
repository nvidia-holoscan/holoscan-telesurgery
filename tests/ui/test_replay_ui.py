# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay visibility and Stop use the same dashboard ownership and input gates."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import FrankaSimulation

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
async def test_replay_requires_matching_recording_and_ownership_and_escape_discards_reply():
    robot = {
        "id": "node:franka",
        "name": "Franka",
        "kind": "franka-sim",
        "simulation": True,
        "status": "online",
        "state": {"sequence": 1},
        "controls": controls(FrankaSimulation({"uri": "unused"}), {"motion_enabled": True}),
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
                result = {
                    "request": ["jog", {"translation": [1, 0, 0], "rotation": [0, 0, 0]}],
                    "speed_deg_s": 3,
                    "elapsed": 0.1,
                    "done": False,
                }
            elif method.startswith("replay."):
                result = True
            else:
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
            context = await browser.new_context(bypass_csp=True)
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
                    "id": "franka/keyboard",
                    "environment": "franka",
                    "device": "keyboard",
                    "task": "Scan",
                    "streams": ["franka"],
                }
            ]
            await page.wait_for_timeout(1100)
            await expect(control).to_be_hidden()
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await expect(control).to_be_visible()
            await control.click()
            await asyncio.wait_for(reading.wait(), 3)
            await expect(page.get_by_label("Franka input", exact=True)).to_be_disabled()
            await page.keyboard.press("Escape")
            gate.set()
            await page.wait_for_timeout(250)
            assert any(c["action"] == "replay.cancel" for c in calls)
            assert not any(c["action"] == "robot.move" for c in calls)
            await expect(page.get_by_label("Franka input", exact=True)).to_be_enabled()
            await page.get_by_role("button", name="Release control", exact=True).click()
            await expect(control).to_be_hidden()
            assert not errors
        finally:
            gate.set()
            await browser.close()
