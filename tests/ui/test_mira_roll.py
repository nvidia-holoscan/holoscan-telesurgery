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
            await expect(page.locator(".keyboard-mapping")).to_contain_text("Left Roll")
            await expect(page.locator(".keyboard-mapping")).to_contain_text("Right Roll")
            await page.keyboard.down("t")
            await page.wait_for_timeout(80)
            await page.keyboard.down("h")
            await page.wait_for_timeout(650)
            assert await page.evaluate("moves.at(-1)") == {
                "left": [0, 0, 0, 0, 1],
                "right": [0, 0, 0, 0, -1],
            }
            await page.keyboard.up("t")
            await page.keyboard.up("h")
            await page.wait_for_timeout(100)
            assert await page.evaluate("stops") == 1
            count = await page.evaluate("moves.length")
            await page.wait_for_timeout(150)
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
            await page.get_by_label("MIRA input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
            await page.evaluate("pad.buttons[10].pressed=pad.buttons[11].pressed=true")
            await expect(page.locator(".gamepad-mapping")).to_contain_text("Left Roll")
            await page.evaluate("pad.buttons[4].pressed=true;pad.axes=[1,-1,1,1]")
            await page.wait_for_timeout(160)
            assert await page.evaluate("moves.at(-1)") == {
                "left": [0, 0, 0, 0, 1],
                "right": [0, 0, 0, 0, -1],
            }
            await page.evaluate("pad.buttons[10].pressed=false")
            await expect(page.locator(".gamepad-status")).to_contain_text("Release")
            count = await page.evaluate("moves.length")
            await page.wait_for_timeout(150)
            assert await page.evaluate("moves.length") == count
            assert await page.evaluate("stops") == 1
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()
