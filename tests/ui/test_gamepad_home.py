# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Home requires an uninterrupted, deliberate hold and neutral controls."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@asynccontextmanager
async def controller_page(*, initially_held=None, button_count=17, controller="DualSense"):
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
                """async ({initiallyHeld, buttonCount, controller}) => {
                document.hasFocus=()=>true;
                window.pad={id:controller,index:0,mapping:'standard',connected:true,
                    axes:[0,0,0,0],buttons:Array.from({length:buttonCount},
                        (_,i)=>({pressed:i===initiallyHeld}))};
                navigator.getGamepads=()=>[pad];window.homes=0;window.canHome=true;
                const {gamepadInput}=await import('/gamepad.js');
                window.input=gamepadInput({name:'MIRA',controls:{groups:{left:5,right:5}}},
                    async()=>{},async()=>{},()=>1,()=>20,
                    {home:{available:()=>canHome,run:async()=>{homes++}}});
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""",
                {
                    "initiallyHeld": initially_held,
                    "buttonCount": button_count,
                    "controller": controller,
                },
            )
            await page.clock.run_for(50)
            selector = page.get_by_label("MIRA input", exact=True)
            await selector.select_option("0")
            await page.clock.run_for(50)
            yield page
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("button,label", [(16, "PS button"), (9, "Options")])
@pytest.mark.parametrize(
    "interruption", ["focus", "access", "stick", "enable", "disconnect", "stop"]
)
async def test_home_hold_cannot_survive_interruption_or_repeat(interruption, button, label):
    async with controller_page() as page:
        status = page.locator(".gamepad-status")
        await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
        # A tap does nothing.
        await page.evaluate("i=>pad.buttons[i].pressed=true", button)
        await page.clock.run_for(150)
        await expect(status).to_contain_text(f"Hold {label}")
        await page.evaluate("i=>pad.buttons[i].pressed=false", button)
        await page.clock.run_for(50)
        await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
        assert await page.evaluate("homes") == 0
        # Restore access after an interruption while the shortcut remains held.
        await page.evaluate("i=>pad.buttons[i].pressed=true", button)
        await page.clock.run_for(200)
        await page.evaluate(
            {
                "focus": "document.hasFocus=()=>false",
                "access": "canHome=false",
                "stick": "pad.axes[0]=1",
                "enable": "pad.buttons[4].pressed=true",
                "disconnect": "pad.connected=false",
                "stop": "input.stop()",
            }[interruption]
        )
        await page.clock.run_for(150)
        await page.evaluate("""() => {
            document.hasFocus=()=>true;canHome=true;pad.connected=true;
            pad.axes.fill(0);pad.buttons[4].pressed=false;
        }""")
        if interruption == "disconnect":
            await page.clock.run_for(50)
            await page.get_by_label("MIRA input", exact=True).select_option("0")
        await page.clock.run_for(1100)
        assert await page.evaluate("homes") == 0
        # A fresh, full hold requests Home exactly once, never early or repeatedly.
        await page.evaluate("i=>pad.buttons[i].pressed=false", button)
        await page.clock.run_for(50)
        await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
        await page.evaluate("i=>pad.buttons[i].pressed=true", button)
        await page.clock.run_for(1000)
        assert await page.evaluate("homes") == 0
        await page.clock.run_for(50)
        assert await page.evaluate("homes") == 1
        await page.clock.run_for(1500)
        assert await page.evaluate("homes") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("button", [16, 9])
async def test_home_button_held_on_selection_requires_release(button):
    async with controller_page(initially_held=button) as page:
        await page.clock.run_for(1500)
        assert await page.evaluate("homes") == 0
        await expect(page.locator(".gamepad-status")).to_contain_text("Release")
        await page.evaluate("i=>pad.buttons[i].pressed=false", button)
        await page.clock.run_for(50)
        await page.evaluate("i=>pad.buttons[i].pressed=true", button)
        await page.clock.run_for(1050)
        assert await page.evaluate("homes") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["swap", "overlap", "after_home"])
async def test_home_shortcuts_cannot_share_hold_time_or_retrigger(change):
    async with controller_page() as page:
        await page.evaluate("pad.buttons[16].pressed=true")
        await page.clock.run_for(1050 if change == "after_home" else 750)
        expected = 1 if change == "after_home" else 0
        assert await page.evaluate("homes") == expected
        await page.evaluate("pad.buttons[9].pressed=true")
        if change == "swap":
            await page.evaluate("pad.buttons[16].pressed=false")
        await page.clock.run_for(1500)
        assert await page.evaluate("homes") == expected
        # Releasing only one button cannot rearm the other.
        await page.evaluate("pad.buttons[16].pressed=false")
        await page.clock.run_for(1500)
        assert await page.evaluate("homes") == expected
        await page.evaluate("pad.buttons[9].pressed=false")
        await page.clock.run_for(50)
        await page.evaluate("pad.buttons[9].pressed=true")
        await page.clock.run_for(1050)
        assert await page.evaluate("homes") == expected + 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "controller,label",
    [("DualSense", "Options"), ("Xbox", "Menu ☰"), ("Nintendo Switch Pro Controller", "+")],
)
async def test_menu_fallback_without_exposed_logo_button(controller, label):
    async with controller_page(button_count=16, controller=controller) as page:
        await page.evaluate("pad.buttons[9].pressed=true")
        await page.clock.run_for(100)
        await expect(page.locator(".gamepad-status")).to_contain_text(f"Hold {label}")
        await page.clock.run_for(950)
        assert await page.evaluate("homes") == 1
