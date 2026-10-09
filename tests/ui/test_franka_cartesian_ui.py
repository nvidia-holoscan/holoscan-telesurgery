# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cartesian gamepad input controls the tool without selecting joint banks."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@asynccontextmanager
async def controller_page(gripper=False, kind="franka-sim"):
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
                """async ({gripper, kind}) => {
                document.hasFocus=()=>true;
                window.pad={id:'DualSense',index:0,mapping:'standard',connected:true,
                    axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false}))};
                navigator.getGamepads=()=>pad.connected?[pad]:[];
                window.moves=[];window.stops=0;window.holdReply=false;
                const {gamepadInput}=await import('/gamepad.js');
                window.input=gamepadInput({name:'Robot',kind,
                    state:{grippers:{hand:1}},
                    controls:{groups:{joints:7},cartesian:{frame:'base'},
                        grippers:gripper?['hand']:[]}},
                    (command,mode)=>{moves.push({command,mode});return holdReply
                        ?new Promise(resolve=>window.reply=resolve):Promise.resolve()},
                    async()=>{stops++},()=>1,()=>20);
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""",
                {"gripper": gripper, "kind": kind},
            )
            await page.clock.run_for(50)
            await page.get_by_label("Robot input", exact=True).select_option("0")
            await page.clock.run_for(50)
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            yield page
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "franka"])
@pytest.mark.parametrize(
    "axis,button,component,index,sign",
    [
        (0, None, "translation", 1, -1),
        (1, None, "translation", 0, -1),
        (3, None, "translation", 2, -1),
        (2, None, "rotation", 2, -1),
        (None, 14, "rotation", 0, 1),
        (None, 15, "rotation", 0, -1),
        (None, 12, "rotation", 1, -1),
        (None, 13, "rotation", 1, 1),
    ],
)
async def test_cartesian_axes_and_release(axis, button, component, index, sign, kind):
    async with controller_page(kind=kind) as page:
        await expect(page.get_by_label("Robot gamepad joints")).to_be_hidden()
        await expect(page.locator(".franka-joint-group")).to_have_count(0)
        # Neither shoulder button is needed for Cartesian input.
        await page.evaluate(
            """({axis,button})=>{
            if(axis!==null)pad.axes[axis]=1;
            if(button!==null)pad.buttons[button].pressed=true;
        }""",
            {"axis": axis, "button": button},
        )
        await page.clock.run_for(50)
        command = {"translation": [0, 0, 0], "rotation": [0, 0, 0]}
        command[component][index] = sign
        assert await page.evaluate("moves.at(-1)") == {"mode": "jog", "command": command}
        await expect(page.locator('.cartesian-mapping kbd[data-active="true"]')).to_have_count(1)
        await page.evaluate("pad.axes.fill(0);pad.buttons.forEach(b=>b.pressed=false)")
        await page.clock.run_for(50)
        assert await page.evaluate("stops") == 1
        count = await page.evaluate("moves.length")
        await page.clock.run_for(500)
        assert await page.evaluate("moves.length") == count


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "franka"])
@pytest.mark.parametrize("interruption", ["blur", "disconnect", "permission", "delay", "stop"])
async def test_cartesian_input_requires_neutral_after_interruption(interruption, kind):
    async with controller_page(kind=kind) as page:
        await page.evaluate("pad.axes[3]=-1")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.length") == 1
        if interruption == "delay":
            await page.clock.fast_forward(500)
        else:
            await page.evaluate(
                {
                    "blur": "document.hasFocus=()=>false",
                    "disconnect": "pad.connected=false",
                    "permission": "input.update(true,false)",
                    "stop": "input.stop()",
                }[interruption]
            )
            await page.clock.run_for(50)
        assert await page.evaluate("stops") == 1
        await page.evaluate("document.hasFocus=()=>true;pad.connected=true;input.update(true,true)")
        await page.clock.run_for(50)
        if interruption == "disconnect":
            await page.get_by_label("Robot input", exact=True).select_option("0")
        await page.clock.run_for(100)
        assert await page.evaluate("moves.length") == 1
        await page.evaluate("pad.axes.fill(0)")
        await page.clock.run_for(50)
        await page.evaluate("pad.axes[3]=-1")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.length") == 2


@pytest.mark.asyncio
async def test_hand_toggle_is_edge_triggered_and_stops_at_feedback_or_stop():
    async with controller_page(gripper=True) as page:
        await page.evaluate("pad.buttons[2].pressed=true")
        await page.clock.run_for(150)
        assert await page.evaluate("moves.map(m=>m.command.velocity.hand)") == [-0.2] * 3
        await page.evaluate("input.feedback({grippers:{hand:0}})")
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 1
        # Holding Square never repeatedly toggles. Release and press to reopen.
        assert await page.evaluate("moves.length") == 3
        await page.evaluate("pad.buttons[2].pressed=false")
        await page.clock.run_for(50)
        await page.evaluate("pad.buttons[2].pressed=true")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.at(-1).command.velocity.hand") == 0.2
        await page.evaluate("input.stop()")
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 2


@pytest.mark.asyncio
async def test_fixed_tool_has_no_gripper_binding_and_slow_reply_never_queues():
    async with controller_page() as page:
        await page.evaluate("pad.buttons[2].pressed=true")
        await page.clock.run_for(100)
        assert await page.evaluate("moves") == []
        await page.evaluate("holdReply=true;pad.axes[0]=1")
        await page.clock.run_for(150)
        assert await page.evaluate("moves.length") == 1
        await page.evaluate("pad.axes.fill(0)")
        await page.clock.run_for(50)
        await page.evaluate("reply()")
        await page.clock.run_for(100)
        assert await page.evaluate("moves.length") == 1
        assert await page.evaluate("stops") == 1


@pytest.mark.asyncio
async def test_slow_reply_resamples_without_an_extra_poll_period_or_queued_input():
    async with controller_page() as page:
        await page.evaluate("holdReply=true;pad.axes[0]=1")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.length") == 1
        await page.clock.run_for(140)
        assert await page.evaluate("moves.length") == 1
        # Read the current direction immediately after the reply, while keeping
        # the 20 Hz maximum. Do not wait another 50 ms or replay the old stick.
        await page.evaluate("pad.axes[0]=-1;reply()")
        await page.clock.run_for(1)
        assert await page.evaluate("moves.length") == 2
        assert await page.evaluate("moves.at(-1).command.translation") == [0, 1, 0]
        await page.evaluate("pad.axes.fill(0);reply()")
        await page.clock.run_for(150)
        assert await page.evaluate("moves.length") == 2
        assert await page.evaluate("stops") == 1
