# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Taps finish one step; held keys jog continuously without queued robot motion."""

import asyncio
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("percent", [1, 20, 100])
@pytest.mark.parametrize("simulation", [False, True])
async def test_joint_button_and_key_are_single_steps(tmp_path, percent, simulation):
    speed_value = FRANKA_SPEED["max"] * percent / 100
    step_size = speed_value * 0.05
    robot = {
        "id": "node:franka",
        "name": "Franka",
        "kind": "franka-sim" if simulation else "franka",
        "status": "online",
        "simulation": simulation,
        "stale": False,
        "controls": {
            "inputs": ["buttons", "keyboard", "gamepad"],
            "groups": {"joints": 7},
            "step_deg": 0.4,
            "default_step_deg": 1,
            "max_step_deg": 5,
            "home_deg": {"joints": FRANKA_HOME},
            "speed_deg_s": FRANKA_SPEED,
        },
        "state": {"joints_deg": {"joints": [0] * 7}, "control_active": False, "sequence": 1},
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
    calls, errors = [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            call = json.loads(request.request.post_data)
            if call["action"] != "robot.renew":
                calls.append(call)
            if call["action"] == "robot.move":
                robot["state"]["control_active"] = True
                robot["state"]["home_active"] = call["params"].get("mode") == "home"
                robot["state"]["sequence"] += 1
            if call["action"] in {"robot.hold", "robot.release"}:
                robot["state"]["control_active"] = False
                robot["state"]["home_active"] = False
                robot["state"]["sequence"] += 1
            await request.fulfill(json={"result": dict(robot["state"])})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    def moves():
        return [c for c in calls if c["action"] == "robot.move"]

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})

            async def wait_moves(count):
                async with asyncio.timeout(3):
                    while len(moves()) < count:
                        await page.clock.run_for(50)

            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("http://localhost:8777/**", route)
            # CI scheduling must not impersonate a stalled input timer.
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await expect(page.get_by_label("Franka input", exact=True)).to_have_value("keyboard")
            await expect(page.get_by_role("button", name="Stop", exact=True)).to_be_enabled()
            await expect(page.get_by_label("Franka joint step", exact=True)).to_have_count(0)
            speed = page.get_by_label("Franka arm speed", exact=True)
            await expect(speed).to_have_value("20")
            await expect(speed).to_have_attribute("min", "1")
            await expect(speed).to_have_attribute("max", "100")
            await speed.focus()
            await speed.evaluate("(s,v)=>{s.value=v;s.dispatchEvent(new Event('input'))}", percent)
            await speed.press("Enter")
            await expect(speed).to_have_value(str(percent))
            plus = page.get_by_role("button", name="Franka joints 5 increase (T)", exact=True)
            await plus.click()
            await page.clock.run_for(100)
            assert len(moves()) == 1
            assert moves()[0]["params"] == {
                "id": robot["id"],
                "command": {"joints": [0, 0, 0, 0, step_size, 0, 0]},
                "mode": "step",
                "speed_deg_s": speed_value,
            }
            assert not any(c["action"] == "robot.hold" for c in calls)
            # A held input must promote a still-active step into a jog. Physical
            # tracking need not report idle before continuous input can begin.
            await plus.hover()
            await page.mouse.down()
            await wait_moves(4)
            assert moves()[1]["params"]["mode"] == "step"
            assert all(c["params"]["mode"] == "jog" for c in moves()[2:])
            await page.mouse.up()
            await page.clock.run_for(150)
            assert calls[-1]["action"] == "robot.hold"
            count = len(moves())
            await page.clock.run_for(700)
            assert len(moves()) == count  # Release stops jogging, with no queued input.
            await page.keyboard.down("t")
            await page.clock.run_for(100)
            await page.keyboard.down("t")  # OS autorepeat must not duplicate a step.
            assert len(moves()) == count + 1
            assert moves()[-1]["params"]["mode"] == "step"
            await wait_moves(count + 4)
            assert all(c["params"]["mode"] == "jog" for c in moves()[count + 1 :])
            await page.keyboard.press("g")  # An additional held key is discarded.
            for move in moves():
                delta = move["params"]["command"]["joints"][4]
                if move["params"]["mode"] == "step":
                    assert delta == pytest.approx(step_size)
                else:
                    assert 0 < delta <= step_size * 2
                assert move["params"]["speed_deg_s"] == speed_value
            await page.keyboard.up("t")
            await page.clock.run_for(150)
            assert calls[-1]["action"] == "robot.hold"
            count = len(moves())
            await page.clock.run_for(700)
            assert len(moves()) == count
            await page.keyboard.press("Escape")
            await page.clock.run_for(100)
            assert calls[-1]["action"] == "robot.hold"
            # Slider endpoints respect node limits and never send motion.
            count = len(moves())
            await speed.focus()
            await speed.press("End")
            await speed.press("ArrowRight")
            await expect(speed).to_have_value("100")
            await speed.press("Home")
            await speed.press("ArrowLeft")
            await expect(speed).to_have_value("1")
            await speed.evaluate("(s,v)=>{s.value=v;s.dispatchEvent(new Event('input'))}", percent)
            await speed.press("Enter")
            assert len(moves()) == count
            # Home is one fixed-pose request, with manual input paused until
            # completion. Escape stops it while retaining ownership.
            await page.clock.run_for(2000)  # Let the Stop indicator finish before Home.
            await page.get_by_role("button", name="Home", exact=True).click()
            await expect(page.get_by_role("button", name="Going home…")).to_be_disabled()
            await page.clock.run_for(50)
            assert moves()[-1]["params"] == {
                "id": robot["id"],
                "command": {},
                "mode": "home",
                "speed_deg_s": speed_value,
            }
            await expect(plus).to_be_disabled()
            await page.keyboard.press("t")
            await page.clock.run_for(100)
            assert len(moves()) == count + 1
            await page.get_by_role("button", name="Stop", exact=True).click()
            await expect(page.get_by_role("button", name="Home", exact=True)).to_be_enabled()
            assert calls[-1]["action"] == "robot.hold"
            robot["error"] = "Franka Home did not reach its target before timeout"
            await page.clock.run_for(1000)
            await expect(page.locator("#robots .status")).to_have_text("Control error")
            await expect(page.locator("#robots .status")).to_have_class("status error")
            await expect(plus).to_be_disabled()
            robot["error"] = ""
            await page.clock.run_for(1000)
            await expect(page.locator("#robots .status")).to_have_text("Available")
            await expect(page.locator("#robots .status")).to_have_class("status online")
            await page.screenshot(path=str(tmp_path / "franka-steps.png"), full_page=True)
            assert not errors
        finally:
            await browser.close()
