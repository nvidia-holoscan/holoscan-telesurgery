# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA tool mode sends bounded XYZ commands and stops on release or mode changes."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("device", ["keyboard", "gamepad"])
async def test_mira_tool_mode_and_release(device):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()

            async def route(request):
                path = request.request.url.removeprefix("http://localhost:8777/")
                if path:
                    await request.fulfill(path=STATIC / path)
                else:
                    await request.fulfill(body="<main></main>", content_type="text/html")

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            assert await page.evaluate(
                """async () => {
                    const {miraToolJog} = await import('/robot-input.js');
                    const robot = {controls: {max_step_deg: 5,
                        mira_cartesian: {linear_step_mm: 5, angular_step_deg: 1,
                            roll_step_deg: 5}}};
                    return miraToolJog(robot, {right: [0, 0, 0, 5, 5]}).right;
                }"""
            ) == [0, 0, 0, 1, 5]
            await page.evaluate(
                """async device => {
                document.hasFocus=()=>true;
                window.moves=[];window.stops=0;
                const robot={name:'MIRA',controls:{groups:{left:5,right:5},max_step_deg:1,
                    mira_cartesian:{linear_step_mm:0.5,angular_step_deg:1,axes:['X','Y','Z','Elbow','Roll']}}};
                const stop=async()=>stops++;
                if(device==='keyboard'){
                    const {keyboardInput}=await import('/keyboard.js');
                    window.input=keyboardInput(robot,async(command,continuous,mode)=>moves.push({command,mode}),stop,()=>1);
                }else{
                    window.pad={id:'Test',index:0,mapping:'standard',connected:true,
                        axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false}))};
                    navigator.getGamepads=()=>[pad];
                    const {gamepadInput}=await import('/gamepad.js');
                    window.input=gamepadInput(robot,async(command,mode)=>moves.push({command,mode}),stop,()=>1);
                    document.body.append(input.select);
                }
                document.body.append(input.element);input.update(true,true);
            }""",
                device,
            )
            if device == "gamepad":
                await page.get_by_label("MIRA input", exact=True).select_option("0")
            await page.get_by_label(f"MIRA {device} mode").select_option("mira-tool")
            await page.locator("select").evaluate_all("els=>els.forEach(e=>e.blur())")
            await page.wait_for_timeout(100)
            if device == "keyboard":
                await page.keyboard.down("q")
                await page.keyboard.down("w")
            else:
                await page.evaluate("pad.buttons[4].pressed=true;pad.axes=[1,-1,0,0]")
            await page.wait_for_function("moves.length>=2")
            result = await page.evaluate("moves.at(-1)")
            assert result["mode"] == "cartesian"
            assert sum(v * v for v in result["command"]["left"][:3]) == pytest.approx(0.25)
            assert result["command"]["right"] == [0] * 5
            if device == "keyboard":
                await page.keyboard.up("q")
                await page.keyboard.up("w")
            else:
                await page.evaluate("pad.buttons[4].pressed=false;pad.axes.fill(0)")
            await page.wait_for_function("stops>0")
            count = await page.evaluate("moves.length")
            await page.wait_for_timeout(150)
            assert await page.evaluate("moves.length") == count
            await page.get_by_label(f"MIRA {device} mode").select_option("joints")
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()
