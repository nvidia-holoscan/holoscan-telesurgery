# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Gamepad tool and joint modes match their labels and stop before switching."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery.controller.input import Inputs

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@asynccontextmanager
async def controller_page(gripper=False, kind="franka-sim", controller="DualSense"):
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
                """async ({gripper, kind, controller}) => {
                document.hasFocus=()=>true;
                window.pad={id:controller,index:0,mapping:'standard',connected:true,
                    axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false}))};
                navigator.getGamepads=()=>pad.connected?[pad]:[];
                window.moves=[];window.stops=0;window.holdReply=false;
                const {gamepadInput}=await import('/gamepad.js');
                window.input=gamepadInput({name:'Robot',kind,
                    state:{grippers:{hand:1}},
                    controls:{groups:{joints:kind==='versius-sim'?8:7},cartesian:{frame:'base'},
                        grippers:gripper?['hand']:[]}},
                    (command,mode)=>{moves.push({command,mode});return holdReply
                        ?new Promise(resolve=>window.reply=resolve):Promise.resolve()},
                    ()=>{stops++;return window.holdStop
                        ?new Promise(resolve=>window.stopped=resolve):Promise.resolve()},
                    ()=>1,()=>20);
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""",
                {"gripper": gripper, "kind": kind, "controller": controller},
            )
            await page.clock.run_for(50)
            await page.get_by_label("Robot input", exact=True).select_option("0")
            await page.clock.run_for(50)
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            yield page
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "franka", "versius-sim"])
@pytest.mark.parametrize(
    "axis,value,button,key,component,index,sign",
    [
        (0, -1, None, "a", "translation", 1, 1),
        (0, 1, None, "d", "translation", 1, -1),
        (1, -1, None, "w", "translation", 0, 1),
        (1, 1, None, "s", "translation", 0, -1),
        (3, -1, None, "r", "translation", 2, 1),
        (3, 1, None, "f", "translation", 2, -1),
        (2, -1, None, "q", "rotation", 2, 1),
        (2, 1, None, "e", "rotation", 2, -1),
        (None, 0, 14, "left", "rotation", 0, 1),
        (None, 0, 15, "right", "rotation", 0, -1),
        (None, 0, 12, "up", "rotation", 1, -1),
        (None, 0, 13, "down", "rotation", 1, 1),
    ],
)
async def test_cartesian_axes_and_release(axis, value, button, key, component, index, sign, kind):
    # Standard gamepads share these axes and button positions. Device labels and
    # raw Nintendo HID normalization have their own browser tests.
    async with controller_page(kind=kind) as page:
        await expect(page.get_by_label("Robot gamepad mode")).to_have_value("cartesian")
        await expect(page.get_by_label("Robot gamepad mode")).to_be_visible()
        await expect(page.locator(".franka-joint-group")).to_have_count(0)
        # Neither shoulder button is needed for Cartesian input.
        await page.evaluate(
            """({axis,value,button})=>{
            if(axis!==null)pad.axes[axis]=value;
            if(button!==null)pad.buttons[button].pressed=true;
        }""",
            {"axis": axis, "value": value, "button": button},
        )
        await page.clock.run_for(50)
        command = {"translation": [0, 0, 0], "rotation": [0, 0, 0]}
        command[component][index] = sign
        assert await page.evaluate("moves.at(-1)") == {"mode": "jog", "command": command}
        native = Inputs(
            {
                "kind": kind,
                "controls": {
                    "groups": {"joints": 8 if kind == "versius-sim" else 7},
                    "cartesian": {"frame": "base"},
                },
            }
        )
        native.from_gamepad([0] * 4, set(), {}, 0)
        axes = [0] * 4
        if axis is not None:
            axes[axis] = value
        assert native.from_gamepad(axes, {button} if button is not None else set(), {}, 0.1) == (
            "jog",
            command,
        )
        native.halt()
        native.keyboard.press(key, 0.2)
        assert native.from_keyboard(0.2) == ("jog", command)
        await expect(page.locator('.cartesian-mapping kbd[data-active="true"]')).to_have_count(1)
        await page.evaluate("pad.axes.fill(0);pad.buttons.forEach(b=>b.pressed=false)")
        await page.clock.run_for(50)
        assert await page.evaluate("stops") == 1
        count = await page.evaluate("moves.length")
        await page.clock.run_for(500)
        assert await page.evaluate("moves.length") == count


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,count", [("franka", 7), ("franka-sim", 7), ("versius-sim", 8)])
async def test_gamepad_mode_change_stops_and_requires_neutral(kind, count):
    async with controller_page(kind=kind) as page:
        mode = page.get_by_label("Robot gamepad mode")
        await expect(mode.locator("option")).to_have_text(
            ["Tool movement", "Individual joints (advanced)"]
        )
        await page.evaluate("pad.axes[1]=-1;window.holdStop=true")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.length") == 1
        await mode.select_option("joints:0")
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 1
        await expect(page.locator(".franka-stick-joint")).to_have_count(count)
        await expect(page.locator(".cartesian-mapping")).to_have_count(0)
        assert await page.evaluate("input.inlineFeedback") is True
        # Centering and moving again while the old stop is pending must not move.
        await page.evaluate("pad.axes.fill(0)")
        await page.clock.run_for(50)
        await page.evaluate("pad.buttons[4].pressed=true;pad.axes[1]=-1")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.length") == 1
        await page.evaluate("window.holdStop=false;stopped()")
        await page.clock.run_for(100)
        assert await page.evaluate("moves.length") == 1
        await page.evaluate("pad.axes.fill(0);pad.buttons.forEach(b=>b.pressed=false)")
        await page.clock.run_for(50)
        await page.evaluate("pad.buttons[4].pressed=pad.buttons[5].pressed=true")
        await page.clock.run_for(50)
        await page.evaluate("count=>pad.axes[count-5]=count===8?-1:1", count)
        await page.clock.run_for(50)
        assert await page.evaluate("moves.at(-1)") == {
            "mode": "jog",
            "command": {"joints": [0] * (count - 1) + [1]},
        }
        await expect(page.locator('.franka-stick-joint kbd[data-active="true"]')).to_have_count(1)
        await mode.select_option("cartesian")
        sent = await page.evaluate("moves.length")
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 2
        assert await page.evaluate("moves.length") == sent
        await expect(page.locator(".franka-stick-joint")).to_have_count(0)
        await expect(page.locator(".cartesian-mapping kbd")).to_have_count(6)
        assert await page.evaluate("input.inlineFeedback") is False
        await page.evaluate("pad.axes.fill(0);pad.buttons.forEach(b=>b.pressed=false)")
        await page.clock.run_for(50)
        await page.evaluate("pad.axes[3]=-1")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.at(-1).command.translation") == [0, 0, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka-sim", "versius-sim"])
async def test_joint_mode_gripper_labels_match_hold_bindings(kind):
    async with controller_page(gripper=True, kind=kind) as page:
        await page.evaluate(
            """async kind => {
            const {gripperControls}=await import('/grippers.js');
            window.grip=gripperControls({name:'Robot',kind,controls:{grippers:['hand']}},
                async()=>{},async()=>{},()=>20);
            document.querySelector('main').append(grip.element);
        }""",
            kind,
        )
        await page.get_by_label("Robot gamepad mode").select_option("joints:0")
        await page.evaluate("grip.update(true,false,input.bindings())")
        await page.clock.run_for(50)
        await expect(page.locator(".grip-toggle")).to_be_hidden()
        await expect(page.locator(".gripper-control kbd")).to_have_text(["□", "○"])
        await expect(page.get_by_role("button", name="Close hand gripper")).to_have_attribute(
            "title", "Hold L1 + □, or hold this on-screen button · Release to stop"
        )
        for button, velocity in [(2, -0.2), (1, 0.2)]:
            await page.evaluate("button=>pad.buttons[button].pressed=true", button)
            before = await page.evaluate("moves.length")
            await page.clock.run_for(50)
            assert await page.evaluate("moves.length") == before
            await page.evaluate("pad.buttons.forEach(b=>b.pressed=false)")
            await page.clock.run_for(50)
            await page.evaluate(
                "button=>pad.buttons[4].pressed=pad.buttons[button].pressed=true", button
            )
            await page.clock.run_for(50)
            assert await page.evaluate("moves.at(-1).command.velocity.hand") == velocity
            await page.evaluate("pad.buttons.forEach(b=>b.pressed=false)")
            await page.clock.run_for(50)
        await page.get_by_label("Robot gamepad mode").select_option("cartesian")
        await page.evaluate("grip.update(true,false,input.bindings())")
        if kind == "franka-sim":
            await expect(page.locator(".grip-toggle")).to_be_visible()
        else:
            await expect(page.locator(".grip-toggle")).to_be_hidden()
            await expect(page.get_by_role("button", name="Close hand gripper")).to_have_attribute(
                "title", "Hold □, or hold this on-screen button · Release to stop"
            )


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
@pytest.mark.parametrize(
    "controller,labels",
    [
        ("DualSense", ["□", "○"]),
        ("Xbox", ["X", "B"]),
        ("Nintendo Switch Pro Controller", ["Y", "A"]),
    ],
)
async def test_versius_grip_has_separate_hold_buttons(controller, labels):
    async with controller_page(gripper=True, kind="versius-sim", controller=controller) as page:
        await page.evaluate("""async () => {
            const {gripperControls}=await import('/grippers.js');
            window.grip=gripperControls({name:'Robot',kind:'versius-sim',controls:{grippers:['hand']}},
                async()=>{},async()=>{},()=>20);
            document.querySelector('main').append(grip.element);
            grip.update(true,false,input.bindings());
            input.feedback({});
        }""")
        await expect(page.locator(".gripper-control kbd")).to_have_text(labels)
        for button in ("Close hand gripper", "Open hand gripper"):
            await expect(page.get_by_role("button", name=button).locator("kbd")).to_be_visible()
        await expect(page.locator(".grip-toggle")).to_be_hidden()
        await page.evaluate("pad.buttons[2].pressed=true")
        await page.clock.run_for(150)
        assert await page.evaluate("moves.map(m=>m.command.velocity.hand)") == [-0.2] * 3
        await page.evaluate("pad.buttons[2].pressed=false")
        await page.clock.run_for(150)
        assert await page.evaluate("stops") == 1
        assert await page.evaluate("moves.length") == 3
        await page.evaluate("pad.buttons[1].pressed=true")
        await page.clock.run_for(150)
        assert await page.evaluate("moves.slice(3).map(m=>m.command.velocity.hand)") == [0.2] * 3
        # Opposite directions cancel, and Stop requires releasing both buttons.
        await page.evaluate("pad.buttons[2].pressed=true")
        await page.clock.run_for(100)
        assert await page.evaluate("stops") == 2
        assert await page.evaluate("moves.length") == 6
        await page.evaluate("pad.buttons[2].pressed=false")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.at(-1).command.velocity.hand") == 0.2
        await page.evaluate("input.stop()")
        count = await page.evaluate("moves.length")
        await page.clock.run_for(150)
        assert await page.evaluate("moves.length") == count
        await page.evaluate("pad.buttons[1].pressed=false")
        await page.clock.run_for(50)
        await page.evaluate("pad.buttons[1].pressed=true")
        await page.clock.run_for(50)
        assert await page.evaluate("moves.length") == count + 1


@pytest.mark.asyncio
async def test_versius_grip_release_preserves_stick_movement():
    async with controller_page(gripper=True, kind="versius-sim") as page:
        await page.evaluate("pad.axes[1]=-1;pad.buttons[2].pressed=true")
        await page.clock.run_for(100)
        assert await page.evaluate("moves.map(m=>m.mode)") == ["grip", "jog"]
        await page.evaluate("pad.buttons[2].pressed=false")
        await page.clock.run_for(100)
        assert await page.evaluate("moves[2]") == {
            "mode": "grip",
            "command": {"velocity": {"hand": 0}},
        }
        assert await page.evaluate("moves[3].mode") == "jog"
        assert await page.evaluate("stops") == 0
        await page.evaluate("pad.axes.fill(0)")
        await page.clock.run_for(50)
        assert await page.evaluate("stops") == 1


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
