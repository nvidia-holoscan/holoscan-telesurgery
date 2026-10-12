# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""MIRA speed percentages control independent, bounded rates in both input modes."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
async def test_independent_speeds_timing_and_edit_interruption():
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
            await page.evaluate("""async () => {
                document.hasFocus=()=>true;
                const {armSpeed,rollSpeed,gripSpeed}=await import('/robot-input.js');
                window.robot={id:'mira',name:'MIRA',controls:{groups:{left:5,right:5},
                    grippers:['left','right'],max_step_deg:5,default_step_deg:1,
                    grip_speed_pct_s:{min:1,max:50,default:20}}};
                window.moves=[];window.stops=0;
                const stop=()=>{stops++;return Promise.resolve()};
                window.speeds=[armSpeed,rollSpeed,gripSpeed].map(create=>
                    create(robot,()=>window.input?.stop()));
                document.querySelector('main').append(...speeds.map(s=>s.element));
                window.defaults=speeds.map(s=>s.element.querySelector('input').value);
                for (const [i,value] of [40,10,60].entries()) {
                    const slider=speeds[i].element.querySelector('input');
                    slider.value=value;slider.dispatchEvent(new Event('input'));
                }
                window.increment=(group,index,seconds)=>speeds[index===4?1:0].increment(seconds);
                const {keyboardInput}=await import('/keyboard.js');
                window.input=keyboardInput(robot,async(command,continuous)=>
                    moves.push({command,continuous}),stop,increment);
                document.body.append(input.element);input.update(true,true);
                window.stop=stop;
            }""")
            assert await page.evaluate("defaults") == ["20", "50", "40"]
            await expect(page.get_by_label("MIRA arm speed")).to_have_value("40")
            await expect(page.get_by_label("MIRA roll speed")).to_have_value("10")
            await expect(page.get_by_label("MIRA grip speed")).to_have_value("60")
            await page.keyboard.down("q")
            await page.keyboard.down("t")
            await page.clock.run_for(500)
            assert await page.evaluate("moves.at(-1)") == {
                "command": {"left": [2, 0, 0, 0, 0.5], "right": [0] * 5},
                "continuous": True,
            }
            await page.keyboard.up("q")
            await page.keyboard.up("t")
            await page.clock.run_for(20)
            assert await page.evaluate("stops") == 1
            await page.evaluate("""async () => {
                input.destroy();input.element.remove();moves=[];
                window.pad={id:'DualSense',index:0,mapping:'standard',connected:true,
                    axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false}))};
                navigator.getGamepads=()=>[pad];
                const {gamepadInput}=await import('/gamepad.js');
                window.input=gamepadInput(robot,async(command,mode)=>moves.push({command,mode}),
                    stop,increment,speeds[2].value);
                document.body.append(input.select,input.element);input.update(true,true);
            }""")
            await page.clock.run_for(50)
            await page.get_by_label("MIRA input", exact=True).select_option("0")
            await page.clock.run_for(50)
            await page.evaluate(
                "pad.buttons[4].pressed=pad.buttons[12].pressed=pad.buttons[2].pressed=true;pad.axes[0]=1"
            )
            await page.clock.run_for(200)
            moves = await page.evaluate("moves")
            assert [m["mode"] for m in moves] == ["grip", "jog", "grip", "jog"]
            assert moves[0]["command"] == {"velocity": {"left": 0, "right": -0.3}}
            assert moves[1]["command"] == {"left": [2, 0, 0, 0, 0.5], "right": [0] * 5}
            # Alternating tool updates take 100 ms; the rate remains the same.
            assert moves[3]["command"] == {"left": [4, 0, 0, 0, 1], "right": [0] * 5}
            assert await page.evaluate("speeds[0].increment(1)") == 5
            before = await page.evaluate("stops")
            await page.get_by_label("MIRA roll speed").focus()
            await page.get_by_label("MIRA roll speed").press("ArrowRight")
            await page.get_by_label("MIRA roll speed").press("Enter")
            await page.clock.run_for(250)
            assert await page.evaluate("stops") == before + 1
            assert await page.evaluate("moves.length") == 4
            await expect(page.get_by_label("MIRA arm speed")).to_have_value("40")
            await expect(page.get_by_label("MIRA grip speed")).to_have_value("60")
            # A stalled browser cannot accumulate a catch-up jump or rearm held input.
            await page.evaluate("pad.buttons.forEach(b=>b.pressed=false);pad.axes.fill(0)")
            await page.clock.run_for(50)
            await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
            await page.clock.run_for(50)
            count = await page.evaluate("moves.length")
            await page.clock.fast_forward(500)
            await page.clock.run_for(100)
            assert await page.evaluate("moves.length") == count
        finally:
            await browser.close()
