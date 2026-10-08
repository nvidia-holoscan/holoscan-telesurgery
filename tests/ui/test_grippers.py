# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Gripper actions retain robot permissions and cannot queue input during Home."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import MiraSimulation
from telesurgery_robots.mira.adapter import MiraAdapter

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("simulation", [True, False])
async def test_mira_gripper_buttons_and_home_permissions(simulation, tmp_path):
    adapter = (MiraSimulation if simulation else MiraAdapter)({"uri": "unused"})
    robot = {
        "id": "node:mira",
        "name": "MIRA",
        "kind": "mira-sim" if simulation else "mira",
        "simulation": simulation,
        "status": "online",
        "stale": False,
        "controls": controls(adapter, {"motion_enabled": True}),
        "state": {"joints_deg": {"left": [0] * 6, "right": [0] * 6}, "sequence": 1},
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "session": {
            "id": "surgeon",
            "status": "approved",
            "robot": True,
            "cameras": [],
            "robots": [robot],
        },
    }
    calls, errors = [], []
    reject = False

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            call = request.request.post_data_json
            calls.append(call)
            if reject and call["action"] == "robot.move":
                await request.fulfill(
                    status=400, json={"error": "Controller rejected request: Tools not homed"}
                )
            else:
                await request.fulfill(json={"result": robot["state"]})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await expect(page.get_by_label("MIRA joint step", exact=True)).to_have_value("1")
            await expect(page.get_by_role("button", name="Home", exact=True)).to_be_enabled()
            speed = page.get_by_label("MIRA gripper speed", exact=True)
            await expect(speed).to_have_value("20")
            for arm in ("left", "right"):
                for label, sign in (("Open", 1), ("Close", -1)):
                    control = page.get_by_role("button", name=f"{label} {arm} gripper")
                    await control.hover()
                    before = len(calls)
                    await page.mouse.down()
                    await page.wait_for_timeout(350)
                    await page.mouse.up()
                    await page.wait_for_timeout(100)
                    moves = [c for c in calls[before:] if c["action"] == "robot.move"]
                    assert len(moves) >= 3
                    for move in moves:
                        assert move["params"] == {
                            "id": "node:mira",
                            "mode": "grip",
                            "command": {
                                "velocity": {
                                    "left": sign * 0.2 if arm == "left" else 0,
                                    "right": sign * 0.2 if arm == "right" else 0,
                                }
                            },
                        }
                    assert calls[-1]["action"] == "robot.release"
                    count = len(calls)
                    await page.wait_for_timeout(250)
                    assert not [c for c in calls[count:] if c["action"] == "robot.move"]
            await speed.fill("10")
            await speed.press("Enter")
            await page.locator(".gripper-controls").focus()
            await page.keyboard.down("x")
            await page.keyboard.down("n")
            await page.wait_for_timeout(300)
            assert [c for c in calls if c["action"] == "robot.move"][-1]["params"]["command"] == {
                "velocity": {"left": 0.1, "right": -0.1}
            }
            await page.keyboard.up("x")
            await page.wait_for_timeout(100)
            assert [c for c in calls if c["action"] == "robot.move"][-1]["params"]["command"] == {
                "velocity": {"left": 0, "right": -0.1}
            }
            await page.keyboard.up("n")
            await page.wait_for_timeout(100)
            assert calls[-1]["action"] == "robot.release"
            # A focus loss stops motion; repeated keydown cannot restart it.
            await page.keyboard.down("x")
            await page.wait_for_timeout(100)
            await page.evaluate("window.dispatchEvent(new Event('blur'))")
            await page.wait_for_timeout(100)
            count = len(calls)
            await page.keyboard.down("x")
            await page.wait_for_timeout(250)
            assert not [c for c in calls[count:] if c["action"] == "robot.move"]
            await page.keyboard.up("x")
            robot["state"].update(home_active=True, control_active=True, sequence=2)
            await expect(page.get_by_role("button", name="Open left gripper")).to_be_disabled()
            await expect(page.get_by_role("button", name="Close right gripper")).to_be_disabled()
            robot["state"].update(home_active=False, control_active=False, sequence=3)
            robot["owner"], robot["owner_id"] = "Other", "other"
            await expect(page.locator("#robots .status")).to_contain_text("Other")
            await expect(page.get_by_role("button", name="Open right gripper")).to_be_disabled()
            robot["owner"] = robot["owner_id"] = None
            await expect(page.get_by_role("button", name="Open right gripper")).to_be_enabled()
            reject = True
            before = len([c for c in calls if c["action"] == "robot.move"])
            await page.locator(".gripper-controls").focus()
            await page.keyboard.down("m")
            await expect(page.locator("#notice")).to_contain_text("Tools not homed")
            await page.wait_for_timeout(600)
            assert len([c for c in calls if c["action"] == "robot.move"]) == before + 1
            await page.keyboard.up("m")
            reject = False
            await page.keyboard.down("m")
            await page.wait_for_timeout(150)
            await page.keyboard.up("m")
            await page.wait_for_timeout(100)
            assert calls[-1]["action"] == "robot.release"
            await page.locator("#robots-panel").screenshot(path=str(tmp_path / "mira-grippers.png"))
            state["session"]["robot"] = False
            await expect(page.locator(".gripper-controls")).to_have_count(0)
            assert not errors
        finally:
            await browser.close()
