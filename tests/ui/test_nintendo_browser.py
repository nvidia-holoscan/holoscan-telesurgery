# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Recognized Switch 2 HID input is positional and retains motion interlocks."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
async def test_switch2_browser_mapping_movement_and_disconnect():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route(
                "http://localhost:8777/**",
                lambda route: route.fulfill(
                    path=STATIC / route.request.url.removeprefix("http://localhost:8777/")
                ),
            )
            await page.route(
                "http://localhost:8777/",
                lambda route: route.fulfill(
                    content_type="text/html", body="<!doctype html><html><body></body></html>"
                ),
            )
            await page.goto("http://localhost:8777/")
            await page.evaluate("""async () => {
                const {gamepadInput}=await import('/gamepad.js');
                window.normalize=(await import('/gamepad-mapping.js')).normalizeGamepad;
                document.hasFocus=()=>true;
                window.pad={id:'Nintendo Pro Controller (Vendor: 057e Product: 2069)',
                    index:1,mapping:'',connected:true,axes:[0,0,0,0],
                    buttons:Array.from({length:21},()=>({pressed:false,value:0}))};
                navigator.getGamepads=()=>pad.connected?[pad]:[];
                window.commands=[];window.releases=0;
                window.input=gamepadInput({name:'Robot',kind:'versius-sim',
                    controls:{groups:{joints:8},cartesian:{},grippers:['hand']}},
                    async (command,mode)=>commands.push({mode,command}),()=>releases++);
                document.body.replaceChildren(input.select,input.element);
                input.update(true,true);
            }""")
            await expect(page.locator('option[value="1"]')).to_have_text("Nintendo controller")
            await expect(page.locator('option[value="1"]')).to_be_enabled()
            await page.get_by_label("Robot input", exact=True).select_option("1")
            await page.locator("body").click(position={"x": 700, "y": 100})
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            # Raw HID up is positive: it must become forward/up, just like Sony/Xbox.
            await page.evaluate("pad.axes=[0.6,0.7,-0.5,0.4]")
            await page.wait_for_function('commands.some(c=>c.mode==="jog")')
            command = await page.evaluate('commands.find(c=>c.mode==="jog").command')
            assert command["translation"][0] > 0
            assert command["translation"][1] < 0
            assert command["translation"][2] > 0
            assert command["rotation"][2] > 0
            await page.evaluate("pad.axes.fill(0)")
            await page.wait_for_function("releases>0")
            # Y closes and A opens; Nintendo C and grip paddles do not trigger Home.
            await page.evaluate("commands.length=0;pad.buttons[2].pressed=true")
            await page.wait_for_function('commands.some(c=>c.mode==="grip")')
            assert (
                await page.evaluate('commands.find(c=>c.mode==="grip").command.velocity.hand') < 0
            )
            await page.evaluate("pad.buttons[2].pressed=false")
            await page.wait_for_timeout(180)
            await page.evaluate("commands.length=0;pad.buttons[1].pressed=true")
            await page.wait_for_function('commands.some(c=>c.mode==="grip")')
            assert (
                await page.evaluate('commands.find(c=>c.mode==="grip").command.velocity.hand') > 0
            )
            prior = await page.evaluate("releases")
            await page.evaluate("pad.connected=false")
            await page.wait_for_function("(n)=>releases>n", arg=prior)
            await expect(page.get_by_label("Robot input", exact=True)).to_have_value("keyboard")
            # Unsupported layouts remain unchanged instead of guessing controls.
            assert await page.evaluate("""()=>[
                {...pad,id:'Unknown controller'},
                {...pad,axes:[0,0]},
                {...pad,buttons:pad.buttons.slice(0,17)},
                {...pad,mapping:'standard'},
            ].every(p=>normalize(p)===p)""")
            # Verify all input positions, including D-pad and both Home shortcuts.
            assert await page.evaluate("""()=>{
                const p={...pad,buttons:pad.buttons.map((_,i)=>i)};
                return JSON.stringify(normalize(p).buttons)===
                    JSON.stringify([0,1,2,3,12,4,13,5,14,6,15,7,11,8,10,9,16]);
            }""")
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()
