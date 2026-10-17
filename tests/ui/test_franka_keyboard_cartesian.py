# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Franka keyboard and on-screen input share continuous Cartesian jogging."""

from contextlib import asynccontextmanager

import pytest
from playwright.async_api import expect
from test_franka_cartesian_ui import controller_page


@asynccontextmanager
async def keyboard_page(kind="franka-sim"):
    async with controller_page(kind=kind) as page:
        await page.evaluate(
            """async kind => {
            input.destroy(); document.querySelector('main').replaceChildren();
            const {keyboardInput}=await import('/keyboard.js');
            window.moves=[];window.stops=0;
            window.input=keyboardInput({name:'Robot',kind,
                controls:{groups:{joints:kind==='versius-sim'?8:7},cartesian:{frame:'base'}}},
                (command,continuous)=>{moves.push({command,continuous,at:performance.now()});
                    return holdReply?new Promise(resolve=>window.reply=resolve):Promise.resolve()},
                async()=>{stops++},()=>.2);
            document.querySelector('main').append(input.element);
            input.update(true,true);
        }""",
            kind,
        )
        yield page


@pytest.mark.asyncio
async def test_real_clock_blocked_tap_is_visible_and_never_replayed():
    async with keyboard_page() as page:
        await page.clock.resume()
        await page.evaluate("input.feedback({stopping:true})")
        await page.keyboard.down("w")
        await expect(page.get_by_role("status")).to_contain_text("Input ignored")
        assert await page.evaluate("moves.length") == 0
        await page.evaluate("input.feedback({stopping:false})")
        await page.wait_for_timeout(250)
        assert await page.evaluate("moves.length") == 0
        await page.keyboard.up("w")
        await page.wait_for_timeout(30)
        await page.keyboard.down("w")
        await page.wait_for_function("moves.length > 0")
        await page.keyboard.up("w")
        await page.wait_for_timeout(100)
        count = await page.evaluate("moves.length")
        await page.wait_for_timeout(250)
        assert await page.evaluate("moves.length") == count


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "franka", "versius-sim"])
async def test_all_tool_keys_hold_continuously_and_stop_on_release(kind):
    async with keyboard_page(kind) as page:
        await expect(page.get_by_label("Robot keyboard mode")).to_have_value("cartesian")
        assert not await page.evaluate("input.inlineFeedback")
        for key, component, index, sign in [
            ("w", "translation", 0, 1),
            ("s", "translation", 0, -1),
            ("a", "translation", 1, 1),
            ("d", "translation", 1, -1),
            ("r", "translation", 2, 1),
            ("f", "translation", 2, -1),
            ("q", "rotation", 2, 1),
            ("e", "rotation", 2, -1),
            ("ArrowLeft", "rotation", 0, 1),
            ("ArrowRight", "rotation", 0, -1),
            ("ArrowUp", "rotation", 1, -1),
            ("ArrowDown", "rotation", 1, 1),
        ]:
            await page.evaluate("moves=[];stops=0")
            await page.keyboard.down(key)
            await page.clock.run_for(350)
            moves = await page.evaluate("moves")
            assert len(moves) >= 6  # No initial keyboard-repeat delay.
            expected = {"translation": [0, 0, 0], "rotation": [0, 0, 0]}
            expected[component][index] = sign
            assert all(m["command"] == expected and m["continuous"] for m in moves)
            await page.keyboard.up(key)
            await page.clock.run_for(100)
            assert await page.evaluate("stops") == 1
            assert await page.evaluate("moves.length") == len(moves)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "versius-sim"])
@pytest.mark.parametrize("release_pairs", [False, True])
async def test_key_repeat_keeps_pressed_indicator_and_motion_until_release(kind, release_pairs):
    async with keyboard_page(kind) as page:
        cap = page.get_by_label("Robot Up (R)", exact=True)
        await page.keyboard.down("r")
        await page.clock.run_for(400)
        for _ in range(60):
            # The host's physical keyboard emits up/down pairs less than 9 ms
            # apart, with repeat=false, while native injected holds do not.
            if release_pairs:
                await page.keyboard.up("r")
                await page.clock.run_for(9)
            await page.keyboard.down("r")
            await page.clock.run_for(24 if release_pairs else 33)
            await expect(cap).to_have_attribute("data-pressed", "true")
            await expect(cap).to_be_enabled()
        assert await page.evaluate("stops") == 0
        assert await page.evaluate("moves.length") >= 45
        await page.keyboard.up("r")
        await page.clock.run_for(50)
        await expect(cap).to_have_attribute("data-pressed", "false")
        assert await page.evaluate("stops") == 1
        count = await page.evaluate("moves.length")
        await page.clock.run_for(150)
        assert await page.evaluate("moves.length") == count


@pytest.mark.asyncio
async def test_combined_axes_and_slow_reply_resample_current_held_keys():
    async with keyboard_page() as page:
        await page.evaluate("holdReply=true")
        await page.keyboard.down("w")
        await page.keyboard.down("r")
        await page.clock.run_for(130)
        assert await page.evaluate("moves.length") == 1
        await page.keyboard.up("w")
        await page.clock.run_for(20)  # Confirm a real release, rather than an autorepeat pair.
        await page.keyboard.down("a")
        await page.evaluate("reply()")
        await page.clock.run_for(1)
        moves = await page.evaluate("moves")
        assert len(moves) == 2
        assert moves[-1]["command"] == {"translation": [0, 1, 1], "rotation": [0, 0, 0]}
        assert moves[-1]["at"] - moves[0]["at"] <= 151
        await page.keyboard.up("a")
        await page.keyboard.up("r")
        await page.evaluate("reply();holdReply=false")
        await page.clock.run_for(200)
        assert await page.evaluate("moves.length") == 2
        assert await page.evaluate("stops") == 1


@pytest.mark.asyncio
async def test_early_timer_does_not_skip_a_held_tool_refresh():
    async with keyboard_page("versius-sim") as page:
        # Browser timers truncate fractional delays. A callback just before
        # the 50 ms deadline must wait only the remainder, not another period.
        await page.evaluate("holdReply=true")
        await page.keyboard.down("w")
        await page.clock.run_for(10)
        await page.evaluate(
            """() => {
            const schedule=window.setTimeout;
            window.setTimeout=(callback,delay,...args)=>
                schedule(callback,delay>1?delay-1:delay,...args);
            reply();holdReply=false;
        }"""
        )
        await page.clock.run_for(42)
        moves = await page.evaluate("moves")
        assert len(moves) == 2
        assert 50 <= moves[1]["at"] - moves[0]["at"] <= 52
        await page.keyboard.up("w")
        await page.clock.run_for(100)
        assert await page.evaluate("moves.length") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "franka", "versius-sim"])
@pytest.mark.parametrize("interruption", ["blur", "permission", "stall", "escape"])
async def test_interrupted_keyboard_does_not_resume_held_key(interruption, kind):
    async with keyboard_page(kind) as page:
        await page.keyboard.down("w")
        await page.clock.run_for(100)
        if interruption == "stall":
            await page.clock.fast_forward(500)
        elif interruption == "escape":
            await page.keyboard.press("Escape")
        else:
            await page.evaluate(
                {
                    "blur": "document.hasFocus=()=>false",
                    "permission": "input.update(true,false)",
                }[interruption]
            )
            await page.clock.run_for(50)
        count = await page.evaluate("moves.length")
        await page.evaluate("document.hasFocus=()=>true;input.update(true,true)")
        await page.clock.run_for(300)
        assert await page.evaluate("moves.length") == count
        assert await page.evaluate("stops") == 1
        await page.keyboard.up("w")
        await page.clock.run_for(20)
        await page.keyboard.down("w")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.length") > count
        await page.keyboard.up("w")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "versius-sim"])
async def test_onscreen_hold_and_advanced_joint_mode(kind):
    async with keyboard_page(kind) as page:
        button = page.get_by_role("button", name="Robot Forward (W)", exact=True)
        await button.hover()
        await page.mouse.down()
        await page.clock.run_for(400)
        count = await page.evaluate("moves.length")
        assert count >= 7
        await page.mouse.up()
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 1
        assert await page.evaluate("moves.length") == count
        await page.get_by_label("Robot keyboard mode").select_option("joints:0")
        assert await page.evaluate("input.inlineFeedback")
        count = 8 if kind == "versius-sim" else 7
        await expect(page.locator(".joint-position")).to_have_count(count)
        await expect(page.locator("select option")).to_have_count(2)
        await page.evaluate("moves=[]")
        await page.keyboard.press("q")
        await page.clock.run_for(100)
        moves = await page.evaluate("moves")
        assert len(moves) == 1 and not moves[0]["continuous"]
        assert moves[0]["command"] == {"joints": [0.2] + [0] * (count - 1)}
        if kind == "versius-sim":
            await page.keyboard.press("i")
            await page.clock.run_for(100)
            assert await page.evaluate("moves.at(-1).command") == {"joints": [0] * 7 + [0.2]}
            await page.keyboard.press("k")
            await page.clock.run_for(100)
            assert await page.evaluate("moves.at(-1).command") == {"joints": [0] * 7 + [-0.2]}
