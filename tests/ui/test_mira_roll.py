# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tool roll shares joint input, including release and gamepad rearming."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
async def test_mira_roll_keyboard_and_gamepad():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route(
                "http://localhost:8777/**",
                lambda r: (
                    r.fulfill(body="<html><body></body></html>", content_type="text/html")
                    if r.request.url.endswith("/index.html")
                    else r.fulfill(
                        path=STATIC / r.request.url.removeprefix("http://localhost:8777/")
                    )
                ),
            )
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.goto("http://localhost:8777/index.html")
            await page.evaluate("""async () => {
                document.body.replaceChildren(); document.hasFocus=()=>true;
                window.robot={name:'MIRA',controls:{groups:{left:5,right:5}}};
                window.moves=[];window.stops=0;
                window.send=c=>{moves.push(c);return Promise.resolve()};
                window.stop=()=>{stops++;return Promise.resolve()};
                const {keyboardInput}=await import('./keyboard.js');
                window.input=keyboardInput(robot,send,stop,()=>1);
                document.body.append(input.element);input.update(true,true);
            }""")
            await expect(page.locator(".joint-position")).to_have_count(10)
            await expect(page.get_by_label("MIRA left roll increase (T)")).to_be_visible()
            await expect(page.get_by_label("MIRA right roll decrease (H)")).to_be_visible()
            await page.keyboard.down("t")
            await page.clock.run_for(80)
            await page.keyboard.down("h")
            await page.clock.run_for(650)
            assert await page.evaluate("moves.at(-1)") == {
                "left": [0, 0, 0, 0, 1],
                "right": [0, 0, 0, 0, -1],
            }
            await page.keyboard.up("t")
            await page.keyboard.up("h")
            await page.clock.run_for(100)
            assert await page.evaluate("stops") == 1
            count = await page.evaluate("moves.length")
            await page.clock.run_for(150)
            assert await page.evaluate("moves.length") == count
            await page.evaluate("""async () => {
                input.destroy();document.body.replaceChildren();moves=[];stops=0;
                window.pad={id:'Test',index:0,mapping:'standard',connected:true,axes:[0,0,0,0],
                    buttons:Array.from({length:17},()=>({pressed:false}))};
                navigator.getGamepads=()=>[pad];
                const {gamepadInput}=await import('./gamepad.js');
                window.input=gamepadInput(robot,send,stop,()=>1);
                document.body.append(input.select,input.element);input.update(true,true);
            }""")
            await page.clock.run_for(50)
            await page.get_by_label("MIRA input", exact=True).select_option("0")
            await page.clock.run_for(50)
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate(
                "pad.buttons[4].pressed=pad.buttons[12].pressed=pad.buttons[0].pressed=true"
            )
            await page.clock.run_for(160)
            assert await page.evaluate("moves.at(-1)") == {
                "left": [0, 0, 0, 0, 1],
                "right": [0, 0, 0, 0, -1],
            }
            # One tool can stop while the other keeps rolling.
            await page.evaluate("pad.buttons[12].pressed=false;moves=[]")
            await page.clock.run_for(50)
            await page.wait_for_function("moves.length>0")
            assert await page.evaluate("moves.at(-1)") == {
                "left": [0, 0, 0, 0, 0],
                "right": [0, 0, 0, 0, -1],
            }
            # Opposing face buttons cancel the remaining roll input.
            await page.evaluate("pad.buttons[3].pressed=true")
            await page.clock.run_for(50)
            await page.wait_for_function("stops===1")
            count = await page.evaluate("moves.length")
            await page.clock.run_for(150)
            assert await page.evaluate("moves.length") == count
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["deadman", "disconnect", "blur", "permission"])
async def test_roll_buttons_need_enable_and_stop_on_loss(ending):
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
            await page.evaluate("""async () => {
                document.hasFocus=()=>true;
                window.pad={id:'DualSense',index:0,mapping:'standard',connected:true,
                    axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false}))};
                navigator.getGamepads=()=>[pad];
                window.moves=[];window.stops=0;
                const {gamepadInput}=await import('/gamepad.js');
                window.input=gamepadInput({name:'MIRA',controls:{groups:{left:5,right:5}}},
                    async command=>{moves.push(command)},async()=>{stops++},()=>1);
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""")
            await page.get_by_label("MIRA input", exact=True).select_option("0")
            status = page.locator(".gamepad-status")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            # A roll button held before enabling must be released before arming.
            await page.evaluate("pad.buttons[12].pressed=true")
            await expect(status).to_contain_text("Release roll buttons")
            await page.evaluate("pad.buttons[4].pressed=true")
            await expect(status).to_contain_text("Release L1")
            assert await page.evaluate("moves.length") == 0
            await page.evaluate("pad.buttons[4].pressed=pad.buttons[12].pressed=false")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            # Roll buttons do not change the sticks' joint mapping, even with clicks held.
            await page.evaluate("""() => {
                pad.buttons[4].pressed=pad.buttons[13].pressed=pad.buttons[3].pressed=true;
                pad.buttons[10].pressed=pad.buttons[11].pressed=true;
                pad.axes=[1,0,0,-1];
            }""")
            await page.wait_for_function("moves.length>0")
            assert await page.evaluate("moves.at(-1)") == {
                "left": [1, 0, 0, 0, -1],
                "right": [0, 1, 0, 0, 1],
            }
            # Releasing roll buttons leaves arm input running with zero roll increments.
            await page.evaluate("pad.buttons[13].pressed=pad.buttons[3].pressed=false;moves=[]")
            await page.wait_for_function("moves.length>0")
            assert await page.evaluate("moves.at(-1)") == {
                "left": [1, 0, 0, 0, 0],
                "right": [0, 1, 0, 0, 0],
            }
            assert await page.evaluate("stops") == 0
            await page.evaluate(
                "pad.buttons[13].pressed=pad.buttons[3].pressed=true;pad.axes.fill(0);moves=[]"
            )
            await page.wait_for_function("moves.length>0")
            await page.evaluate(
                {
                    "deadman": "pad.buttons[4].pressed=false",
                    "disconnect": "pad.connected=false",
                    "blur": "document.hasFocus=()=>false",
                    "permission": "input.update(true,false)",
                }[ending]
            )
            await page.wait_for_function("stops===1")
            count = await page.evaluate("moves.length")
            await page.wait_for_timeout(160)
            assert await page.evaluate("moves.length") == count
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()
