# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A stop acknowledgement must block input before slower inventory polling catches up."""

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
async def test_stop_acknowledgement_blocks_repress_with_stale_inventory():
    robot = {
        "id": "node:franka",
        "name": "Franka",
        "kind": "franka-sim",
        "status": "online",
        "simulation": True,
        "stale": False,
        "controls": {"groups": {"joints": 7}, "step_deg": 1, "default_step_deg": 1},
        "state": {"sequence": 1, "control_active": False, "joints_deg": {"joints": [0] * 7}},
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "session": {
            "id": "operator",
            "status": "approved",
            "robot": True,
            "cameras": [],
            "robots": [robot],
        },
    }
    moves = []
    stopped = asyncio.Event()

    async def route(route):
        path = route.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await route.fulfill(json=state)
        elif path == "api/action":
            call = route.request.post_data_json
            result = True
            if call["action"] == "robot.move":
                moves.append(call)
                result = {"sequence": len(moves) + 1, "control_active": True}
            elif call["action"] == "robot.release" and moves:
                result = {"sequence": 100, "control_active": True, "stopping": True}
                stopped.set()
            await route.fulfill(json={"result": result})
        else:
            await route.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            key = page.locator('.key-cap[data-key="g"]')
            await expect(key).to_be_enabled()
            await page.locator(".keyboard-controls").focus()
            await page.keyboard.down("g")
            async with asyncio.timeout(3):
                while len(moves) < 3:
                    await page.wait_for_timeout(25)
            await page.keyboard.up("g")
            await asyncio.wait_for(stopped.wait(), 2)
            await expect(key).to_be_disabled()
            await expect(page.locator(".keyboard-status")).to_have_text("Stopping · Release keys")
            count = len(moves)
            # Polls still return the pre-stop state. A held new key must neither
            # bypass braking nor be queued to run when braking completes.
            await page.keyboard.down("g")
            await page.wait_for_timeout(1100)
            assert len(moves) == count
            await expect(key).to_be_disabled()
            robot["state"] = {"sequence": 101, "control_active": False, "stopping": False}
            await expect(key).to_be_enabled()
            await page.wait_for_timeout(600)
            assert len(moves) == count
            await page.keyboard.up("g")
            await page.keyboard.press("g")
            async with asyncio.timeout(2):
                while len(moves) == count:
                    await page.wait_for_timeout(25)
            assert len(moves) == count + 1
        finally:
            await browser.close()
