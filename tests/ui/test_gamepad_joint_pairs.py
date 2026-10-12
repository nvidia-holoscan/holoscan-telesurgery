# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Either shoulder order works at rest without rearming interrupted input."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@asynccontextmanager
async def controller_page(name="DualSense", kind="mira-sim"):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            async def route(request):
                path = request.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    await request.fulfill(body="<main></main>", content_type="text/html")
                else:
                    await request.fulfill(path=STATIC / path)

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.evaluate(
                """async ({name,kind}) => {
                document.hasFocus=()=>true;
                window.pad={id:name,index:0,mapping:'standard',connected:true,
                    axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false}))};
                navigator.getGamepads=()=>pad.connected?[pad]:[];
                window.moves=[];window.stops=0;window.holdReply=false;
                const {gamepadInput}=await import('/gamepad.js');
                const controls=kind==='franka-sim'?{groups:{joints:7}}:
                    {groups:{left:5,right:5},grippers:['left','right']};
                window.input=gamepadInput({name:'Robot',kind,controls},
                    (command,mode)=>{
                        moves.push({command,mode});
                        return holdReply
                            ?new Promise(resolve=>window.reply=resolve):Promise.resolve();
                    },async()=>{stops++},()=>1,()=>20);
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""",
                {"name": name, "kind": kind},
            )
            await page.clock.run_for(50)
            await page.get_by_label("Robot input", exact=True).select_option("0")
            await page.clock.run_for(50)
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            yield page
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["mira-sim", "franka-sim"])
@pytest.mark.parametrize(
    "name", ["DualSense", "Xbox Wireless Controller", "Nintendo Switch Pro Controller"]
)
@pytest.mark.parametrize("order", [(4, 5), (5, 4), (4, 5, "together")])
async def test_either_shoulder_order_selects_same_joints(name, order, kind):
    async with controller_page(name, kind) as page:
        franka = kind == "franka-sim"
        if not franka:
            await expect(page.locator(".gamepad-roll-arm").nth(1).locator("kbd")).to_have_text(
                {
                    "DualSense": ["△", "✕"],
                    "Xbox Wireless Controller": ["Y", "A"],
                    "Nintendo Switch Pro Controller": ["X", "B"],
                }[name]
            )
        if len(order) == 3:
            await page.evaluate("pad.buttons[4].pressed=pad.buttons[5].pressed=true")
            await page.clock.run_for(50)
        else:
            for button in order:
                await page.evaluate("i=>pad.buttons[i].pressed=true", button)
                await page.clock.run_for(50)
        assert await page.evaluate("moves") == []
        assert await page.evaluate("stops") == 0
        await expect(page.locator('.gamepad-instructions kbd[data-active="true"]')).to_have_text(
            [
                {
                    "DualSense": "L1 + R1",
                    "Xbox Wireless Controller": "LB + RB",
                    "Nintendo Switch Pro Controller": "L + R",
                }[name]
            ]
        )
        await page.evaluate("pad.axes=[1,-1,-1,1]")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.at(-1)") == {
            "mode": "jog",
            "command": {"joints": [0, 0, 0, 0, 1, 1, -1]}
            if franka
            else {"left": [0, 0, 1, 1, 0], "right": [0, 0, -1, -1, 0]},
        }
        if franka:
            await expect(page.get_by_label("Robot gamepad joints")).to_be_hidden()
            await expect(
                page.locator('.franka-stick-joint:has(kbd[data-active="true"]) > span')
            ).to_have_text(["J5", "J6", "J7"])
        # At rest, releasing R1 returns to J1/J2 without releasing L1.
        await page.evaluate("pad.axes.fill(0)")
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 1
        await page.evaluate("pad.buttons[5].pressed=false")
        await page.clock.run_for(50)
        await expect(page.locator('.gamepad-instructions kbd[data-active="true"]')).to_have_text(
            [
                {
                    "DualSense": "L1",
                    "Xbox Wireless Controller": "LB",
                    "Nintendo Switch Pro Controller": "L",
                }[name]
            ]
        )
        await page.evaluate("pad.axes=[1,-1,-1,1]")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.at(-1).command") == (
            {
                "joints": [1, 1, -1, -1, 0, 0, 0],
            }
            if franka
            else {
                "left": [1, 1, 0, 0, 0],
                "right": [-1, -1, 0, 0, 0],
            }
        )
        await page.evaluate("pad.buttons[4].pressed=false;pad.axes.fill(0)")
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 2
        count = await page.evaluate("moves.length")
        await page.clock.run_for(200)
        assert await page.evaluate("moves.length") == count


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["mira-sim", "franka-sim"])
@pytest.mark.parametrize(
    "interruption",
    ["stick", "roll", "grip", "inflight", "blur", "permission", "disconnect", "stop", "delayed"],
)
async def test_mode_change_cannot_rearm_moving_or_interrupted_input(interruption, kind):
    if kind == "franka-sim" and interruption in {"roll", "grip"}:
        pytest.skip("Franka does not advertise separate roll or gripper controls")
    async with controller_page(kind=kind) as page:
        await page.evaluate("pad.buttons[4].pressed=true")
        await page.clock.run_for(50)
        if interruption in {"stick", "roll", "grip", "inflight"}:
            await page.evaluate(
                {
                    "stick": "pad.axes[0]=1",
                    "roll": "pad.buttons[12].pressed=true",
                    "grip": "pad.buttons[15].pressed=true",
                    "inflight": "holdReply=true;pad.axes[0]=1",
                }[interruption]
            )
            await page.clock.run_for(50)
            assert await page.evaluate("moves.length") == 1
            if interruption == "inflight":
                await page.evaluate("pad.axes.fill(0)")
                await page.clock.run_for(50)
        elif interruption == "disconnect":
            await page.evaluate("pad.connected=false")
            await page.clock.run_for(50)
            await page.evaluate("pad.connected=true")
            await page.clock.run_for(50)
            await page.get_by_label("Robot input", exact=True).select_option("0")
        elif interruption == "delayed":
            await page.clock.fast_forward(500)
        else:
            await page.evaluate(
                {
                    "blur": "document.hasFocus=()=>false",
                    "permission": "input.update(true,false)",
                    "stop": "input.stop()",
                }[interruption]
            )
            await page.clock.run_for(50)
            await page.evaluate("document.hasFocus=()=>true;input.update(true,true)")
        count = await page.evaluate("moves.length")
        await page.evaluate("pad.buttons[5].pressed=true")
        await page.clock.run_for(50)
        await expect(page.locator(".gamepad-status")).to_contain_text("Release L1")
        await expect(page.locator('kbd[data-active="true"]')).to_have_count(0)
        assert await page.evaluate("moves.length") == count
        # Neutral inputs and toggling R1 cannot bypass the required release.
        await page.evaluate(
            "pad.axes.fill(0);pad.buttons[12].pressed=pad.buttons[15].pressed=false"
        )
        if interruption == "inflight":
            await page.evaluate("holdReply=false;reply()")
        for pressed in [False, True]:
            await page.evaluate("v=>pad.buttons[5].pressed=v", pressed)
            await page.clock.run_for(50)
        await page.evaluate("pad.axes[0]=1")
        await page.clock.run_for(100)
        assert await page.evaluate("moves.length") == count
        # Releasing L1 and centering allows a deliberate new command.
        await page.evaluate("pad.buttons[4].pressed=false;pad.axes.fill(0)")
        await page.clock.run_for(50)
        await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.at(-1).command") == (
            {
                "joints": [0, 0, 0, 0, 1, 0, 0],
            }
            if kind == "franka-sim"
            else {
                "left": [0, 0, 1, 0, 0],
                "right": [0, 0, 0, 0, 0],
            }
        )
        assert await page.evaluate("moves.length") == count + 1


@pytest.mark.asyncio
async def test_franka_unused_axis_does_not_move_any_joint():
    async with controller_page(kind="franka-sim") as page:
        await page.evaluate("pad.buttons[4].pressed=pad.buttons[5].pressed=true")
        await page.clock.run_for(50)
        await page.evaluate("pad.axes[3]=-1")
        await page.clock.run_for(200)
        assert await page.evaluate("moves") == []
        await expect(page.locator('.franka-stick-joint kbd[data-active="true"]')).to_have_count(0)


@pytest.mark.asyncio
async def test_franka_joint_positions_stay_with_their_axis_and_clear_when_missing():
    async with controller_page(kind="franka-sim") as page:
        await page.evaluate("input.feedback({joints_deg:{joints:[1,2,3,4,5,6,7]}})")
        await expect(page.locator(".gamepad-joint-position")).to_have_text(
            ["1.00", "2.00", "3.00", "4.00", "5.00", "6.00", "7.00"]
        )
        await page.evaluate("pad.buttons[4].pressed=pad.buttons[5].pressed=true")
        await page.clock.run_for(50)
        await expect(page.get_by_label("J7 measured position in degrees", exact=True)).to_have_text(
            "7.00"
        )
        await page.evaluate("input.feedback({targets_deg:{joints:[11,12,13,14,15,16,17]}})")
        await expect(page.get_by_label("J7 target position in degrees", exact=True)).to_have_text(
            "17.00"
        )
        await expect(page.locator(".franka-stick-heading > span:last-child")).to_have_text(
            ["Target °", "Target °"]
        )
        await page.evaluate("input.feedback({})")
        await expect(page.locator(".gamepad-joint-position")).to_have_text(["—"] * 7)
