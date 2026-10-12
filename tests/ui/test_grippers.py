# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Gripper actions retain robot permissions and cannot queue input during Home."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import MiraSimulation
from telesurgery_robots.mira.adapter import MiraAdapter
from test_franka_cartesian_ui import controller_page

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["versius-sim", "mira-sim"])
@pytest.mark.parametrize("interruption", ["release", "blur", "stall", "escape"])
async def test_gripper_keyboard_release_pairs_are_one_hold(kind, interruption):
    async with controller_page() as page:
        await page.evaluate(
            """async kind => {
            input.destroy();document.querySelector('main').replaceChildren();
            const {gripperControls}=await import('/grippers.js');
            moves=[];stops=0;
            window.input=gripperControls({name:'Robot',kind,
                controls:{grippers:kind==='mira-sim'?['left','right']:['hand']}},
                async command=>moves.push({command,at:performance.now()}),
                async()=>{stops++},()=>50);
            document.querySelector('main').append(input.element);
            input.update(true,true);input.element.focus();
        }""",
            kind,
        )
        button = page.get_by_role(
            "button", name=f"Close {'left' if kind == 'mira-sim' else 'hand'} gripper", exact=True
        )
        await page.keyboard.down("z")
        await page.clock.run_for(450)
        for _ in range(60):
            await page.keyboard.up("z")
            await page.clock.run_for(9)
            await page.keyboard.down("z")
            await page.clock.run_for(24)
            await expect(button).to_have_attribute("data-pressed", "true")
        assert await page.evaluate("stops") == 0
        moves = await page.evaluate("moves")
        assert len(moves) >= 48
        arm = "left" if kind == "mira-sim" else "hand"
        assert all(move["command"]["velocity"][arm] == -0.5 for move in moves)
        if interruption == "release":
            await page.keyboard.up("z")
            await page.clock.run_for(20)
        elif interruption == "blur":
            await page.evaluate("window.dispatchEvent(new Event('blur'))")
        elif interruption == "escape":
            await page.keyboard.press("Escape")
        else:
            await page.clock.fast_forward(250)
        assert await page.evaluate("stops") == 1
        count = await page.evaluate("moves.length")
        if interruption != "release":
            # Repeat=false cannot restart input following an interruption.
            for _ in range(5):
                await page.keyboard.up("z")
                await page.clock.run_for(9)
                await page.keyboard.down("z")
                await page.clock.run_for(24)
        await page.clock.run_for(100)
        assert await page.evaluate("moves.length") == count
        await expect(button).to_have_attribute("data-pressed", "false")
        await page.keyboard.up("z")
        await page.clock.run_for(20)
        await page.keyboard.down("z")
        await page.clock.run_for(100)
        assert await page.evaluate("moves.length") > count
        await page.keyboard.up("z")
        await page.clock.run_for(20)


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
            await expect(page.get_by_label("MIRA arm speed", exact=True)).to_have_value("20")
            await expect(page.get_by_role("button", name="Home", exact=True)).to_be_enabled()
            speed = page.get_by_label("MIRA grip speed", exact=True)
            await expect(speed).to_have_value("40")
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
            await speed.focus()
            await speed.evaluate("s => {s.value='20';s.dispatchEvent(new Event('input'))}")
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


@pytest.mark.asyncio
async def test_gamepad_selection_updates_bindings_and_routes_gripper_commands():
    robot = {
        "id": "node:mira",
        "name": "MIRA",
        "kind": "mira-sim",
        "status": "online",
        "controls": controls(MiraSimulation({"uri": "unused"}), {"motion_enabled": True}),
        "state": {"sequence": 1},
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
    calls = []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            calls.append(request.request.post_data_json)
            await request.fulfill(json={"result": robot["state"]})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script("""
                window.pad={id:'Sony Interactive Entertainment DualSense Wireless Controller',
                    index:0,mapping:'standard',connected:true,axes:[0,0,0,0],
                    buttons:Array.from({length:17},()=>({pressed:false}))};
                navigator.getGamepads=()=>[pad];document.hasFocus=()=>true;
            """)
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            selector = page.get_by_label("MIRA input", exact=True)
            await expect(selector.locator("option")).to_have_text(["Keyboard", "Sony DualSense"])
            badges = page.locator(".gripper-control kbd")
            await expect(badges).to_have_text(["Z", "X", "N", "M"])
            await expect(page.locator(".keyboard-controls .gripper-controls")).to_be_visible()
            await selector.select_option("0")
            await expect(badges).to_have_text(["←", "→", "□", "○"])
            await expect(page.locator(".gamepad-controls .gripper-controls")).to_be_visible()
            await expect(selector).to_have_attribute("title", await page.evaluate("pad.id"))
            await expect(page.locator(".gamepad-status")).to_have_text(
                "Hold L1 for arms, roll & grip"
            )
            await page.locator(".gripper-controls").focus()
            await page.keyboard.press("z")
            assert not [c for c in calls if c["action"] == "robot.move"]
            await page.evaluate("pad.buttons[4].pressed=pad.buttons[15].pressed=true")
            for _ in range(40):
                if any(c["action"] == "robot.move" for c in calls):
                    break
                await page.wait_for_timeout(50)
            moves = [c for c in calls if c["action"] == "robot.move"]
            assert moves[-1]["params"]["mode"] == "grip"
            assert moves[-1]["params"]["command"] == {"velocity": {"left": 0.2, "right": 0}}
            await expect(page.get_by_role("button", name="Open left gripper")).to_have_attribute(
                "data-pressed", "true"
            )
            await selector.select_option("keyboard")
            await expect(badges).to_have_text(["Z", "X", "N", "M"])
            assert calls[-1]["action"] == "robot.release"
            count = len([c for c in calls if c["action"] == "robot.move"])
            await page.wait_for_timeout(180)
            assert len([c for c in calls if c["action"] == "robot.move"]) == count
            await page.evaluate("""() => {
                pad.buttons.forEach(b=>b.pressed=false);
                pad.id='Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e Product: 0b13)';
            }""")
            await expect(selector.locator("option")).to_have_text(["Keyboard", "Xbox controller"])
            await selector.select_option("0")
            await expect(badges).to_have_text(["←", "→", "X", "B"])
            await expect(page.locator(".gamepad-status")).to_have_text(
                "Hold LB for arms, roll & grip"
            )
            # Two devices with the same friendly name remain distinguishable.
            await page.evaluate("navigator.getGamepads=()=>[pad,{...pad,index:1}]")
            await expect(selector.locator("option")).to_have_text(
                ["Keyboard", "Xbox controller · 1", "Xbox controller · 2"]
            )
            # Both shortcuts use the same Home action as the on-screen button.
            await expect(page.get_by_role("button", name="Home", exact=True)).to_have_attribute(
                "title",
                "Home · Return to starting pose · "
                "Hold Xbox button or Menu ☰ for 1s with LB released",
            )
            for count, (button, label) in enumerate([(16, "Xbox button"), (9, "Menu")], 1):
                await page.evaluate("i=>pad.buttons[i].pressed=true", button)
                await expect(page.locator(".gamepad-status")).to_contain_text(f"Hold {label}")
                for _ in range(40):
                    homes = [c for c in calls if c.get("params", {}).get("mode") == "home"]
                    if len(homes) == count:
                        break
                    await page.wait_for_timeout(50)
                assert len(homes) == count
                assert homes[-1]["params"]["command"] == {}
                await page.wait_for_timeout(1100)
                assert len([c for c in calls if c.get("params", {}).get("mode") == "home"]) == count
                await page.evaluate("i=>pad.buttons[i].pressed=false", button)
                await expect(page.locator(".gamepad-controls")).to_have_attribute(
                    "data-state", "ready"
                )
        finally:
            await browser.close()
