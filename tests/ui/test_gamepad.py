# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Browser input must stop on release, loss and permission changes without queuing motion."""

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
PAD = """
window.pad = {id: 'Test standard gamepad', index: 0, mapping: 'standard', connected: true,
 axes: [0,0,0,0], buttons: Array.from({length:17}, () => ({pressed:false,value:0}))};
navigator.getGamepads = () => window.pad.connected ? [window.pad] : [];
document.hasFocus = () => true;
"""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,groups",
    [
        ("mira-sim", {"left": 4, "right": 4}),
        ("franka-sim", {"joints": 7}),
        ("franka", {"joints": 7}),
        ("mira", {"left": 4, "right": 4}),
    ],
)
async def test_gamepad_deadman_mapping_disconnect_and_revocation(tmp_path, kind, groups):
    robot = {
        "id": "node:robot",
        "name": "Robot",
        "kind": kind,
        "status": "online",
        "owner": None,
        "controls": {"inputs": ["buttons", "gamepad"], "groups": groups, "step_deg": 0.4},
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "session": {
            "id": "one",
            "status": "approved",
            "robot": True,
            "robots": [robot],
            "cameras": [],
        },
    }
    actions, errors = [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            call = json.loads(request.request.post_data)
            if call["action"] != "robot.renew":
                actions.append(call)
            await request.fulfill(json={"result": True})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 960})
            await page.add_init_script(PAD)
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await page.get_by_label("Robot input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            # Sticks do not move without the deadman; small drift stays in the dead zone.
            await page.evaluate("pad.axes[0]=0.5")
            await page.wait_for_timeout(150)
            assert not [a for a in actions if a["action"] == "robot.move"]
            await page.evaluate("pad.axes[0]=0.1")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate("pad.buttons[4].pressed=true")
            await page.wait_for_timeout(150)
            assert not [a for a in actions if a["action"] == "robot.move"]
            await page.evaluate("pad.axes[0]=1")
            for _ in range(40):
                if any(a["action"] == "robot.move" for a in actions):
                    break
                await page.wait_for_timeout(50)
            moves = [a for a in actions if a["action"] == "robot.move"]
            assert moves
            command = moves[0]["params"]["command"]
            key = next(iter(groups))
            assert command[key][0] == pytest.approx(0.08)
            assert sum(v != 0 for values in command.values() for v in values) == 1
            assert len(command[key]) == groups[key]
            enabled_badges = page.locator('.gamepad-instructions kbd[data-active="true"]')
            await expect(enabled_badges).to_have_text(["LB/L1"])
            if "left" in groups:
                await expect(page.get_by_label("Robot gamepad joints")).to_be_hidden()
                await page.evaluate("pad.axes[2]=-0.575")
                await page.wait_for_timeout(160)
                command = [a for a in actions if a["action"] == "robot.move"][-1]["params"][
                    "command"
                ]
                distance = command["left"][0]
                assert 0.076 <= distance <= 0.16 + 1e-9
                assert command["left"][1:] == [0, 0, 0]
                assert command["right"] == pytest.approx([-distance / 2, 0, 0, 0])
                # Changing joint pairs stops both arms and requires a fresh deadman press.
                await page.evaluate("pad.buttons[5].pressed=true")
                await expect(page.locator(".gamepad-status")).to_contain_text("Release")
                await expect(enabled_badges).to_have_count(0)
                assert actions[-1]["action"] == "robot.hold"
                count = len([a for a in actions if a["action"] == "robot.move"])
                await page.wait_for_timeout(150)
                assert len([a for a in actions if a["action"] == "robot.move"]) == count
                await page.evaluate("pad.buttons[4].pressed=false;pad.axes.fill(0)")
                await expect(page.locator(".gamepad-controls")).to_have_attribute(
                    "data-state", "ready"
                )
                await expect(page.locator(".gamepad-status")).to_have_text(
                    "Hold LB/L1 for movement"
                )
                # R1 selects the pair; it does not replace the L1 enable button.
                await page.evaluate("pad.axes[0]=1")
                await page.wait_for_timeout(150)
                assert len([a for a in actions if a["action"] == "robot.move"]) == count
                await page.evaluate("pad.axes.fill(0)")
                await expect(page.locator(".gamepad-controls")).to_have_attribute(
                    "data-state", "ready"
                )
                await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=0.575;pad.axes[3]=-1")
                await page.wait_for_timeout(160)
                command = [a for a in actions if a["action"] == "robot.move"][-1]["params"][
                    "command"
                ]
                distance = command["right"][3]
                assert 0.076 <= distance <= 0.16 + 1e-9
                assert command["left"] == pytest.approx([0, 0, distance / 2, 0])
                assert command["right"][:3] == [0, 0, 0]
                await expect(enabled_badges).to_have_text(["LB/L1 + RB/R1"])
                await page.evaluate(
                    "pad.buttons[4].pressed=false;pad.buttons[5].pressed=false;pad.axes.fill(0)"
                )
                await expect(page.locator(".gamepad-controls")).to_have_attribute(
                    "data-state", "ready"
                )
                await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
                await page.wait_for_timeout(100)
            # Changing speed stops active input; a held deadman cannot resume.
            step = page.get_by_label("Robot arm speed", exact=True)
            await step.focus()
            await step.press("End")
            await step.press("Enter")
            await expect(page.locator(".gamepad-status")).to_contain_text("Release")
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            assert actions[-1]["action"] == "robot.hold"
            await page.evaluate("pad.buttons[4].pressed=false; pad.axes.fill(0)")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate("pad.buttons[4].pressed=true; pad.axes[0]=-0.575")
            for _ in range(40):
                if len([a for a in actions if a["action"] == "robot.move"]) > count:
                    break
                await page.wait_for_timeout(50)
            moves = [a for a in actions if a["action"] == "robot.move"]
            assert len(moves) > count
            assert moves[count]["params"]["command"][key][0] == pytest.approx(-0.2)
            # Releasing the deadman cancels motion while keeping the remote lock.
            await page.evaluate("pad.buttons[4].pressed=false; pad.axes.fill(0)")
            for _ in range(40):
                if actions[-1]["action"] == "robot.hold":
                    break
                await page.wait_for_timeout(50)
            assert actions[-1]["action"] == "robot.hold"
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.screenshot(path=str(tmp_path / f"{kind}-gamepad.png"))
            # Disconnect and reconnect while pressed must not resume movement.
            await page.evaluate("pad.buttons[4].pressed=true; pad.axes[0]=1")
            await page.wait_for_timeout(150)
            await page.evaluate("pad.connected=false")
            await expect(page.locator(".gamepad-status")).to_contain_text("Choose")
            await page.evaluate("pad.connected=true")
            await expect(page.get_by_label("Robot input", exact=True)).to_have_value("keyboard")
            await page.get_by_label("Robot input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-status")).to_contain_text("Release")
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            # Permission loss stops motion; the patient controls ownership revocation.
            await page.evaluate("pad.buttons[4].pressed=false; pad.axes.fill(0)")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate("pad.buttons[4].pressed=true; pad.axes[0]=1")
            for _ in range(40):
                if len([a for a in actions if a["action"] == "robot.move"]) > count:
                    break
                await page.wait_for_timeout(50)
            releases = len([a for a in actions if a["action"] == "robot.release"])
            holds = len([a for a in actions if a["action"] == "robot.hold"])
            state["session"]["robot"] = False
            await expect(page.locator("#robots-panel")).to_contain_text("View-only access")
            await expect(page.locator("#robots .gamepad-controls")).to_have_count(0)
            for _ in range(40):
                if len([a for a in actions if a["action"] == "robot.hold"]) > holds:
                    break
                await page.wait_for_timeout(50)
            assert len([a for a in actions if a["action"] == "robot.hold"]) > holds
            assert len([a for a in actions if a["action"] == "robot.release"]) == releases
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["release", "access_lost"])
async def test_release_during_slow_command_never_queues_or_replays_motion(ending):
    # Test the input module separately so an intentionally slow network request
    # cannot hide a released deadman behind an awaited response.
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script(PAD)

            async def route(request):
                path = request.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    await request.fulfill(body='<div id="pad"></div>', content_type="text/html")
                else:
                    await request.fulfill(path=STATIC / path)

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.evaluate("""async () => {
              const {gamepadInput}=await import('/gamepad.js');
              window.sent=0;window.stopped=0;
              const input=gamepadInput({name:'MIRA',controls:{groups:{left:4,right:4}}},
                () => {sent++;return new Promise(resolve => window.reply=resolve)},
                async () => {stopped++});
              document.querySelector('#pad').append(input.select,input.element);input.update(true,true);
            }""")
            await page.get_by_label("MIRA input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate("pad.buttons[4].pressed=true; pad.axes[0]=1")
            await page.wait_for_function("sent===1")
            await page.evaluate(
                "pad.buttons[4].pressed=false; pad.axes.fill(0)"
                if ending == "release"
                else "() => {navigator.getGamepads=()=>{"
                "throw new DOMException('Access denied','SecurityError')}}"
            )
            await page.wait_for_function("stopped===1")
            assert await page.evaluate("sent") == 1
            await page.evaluate("reply()")
            await page.wait_for_timeout(150)
            assert await page.evaluate("sent") == 1
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "names,label",
    [
        (("PS5 Controller", "DualSense Wireless Controller"), "Sony DualSense"),
        (("Xbox Wireless Controller", "X-Box One Controller"), "Xbox controller"),
        (
            ("Nintendo Switch Pro Controller", "Nintendo Switch Pro Controller"),
            "Nintendo controller",
        ),
    ],
)
async def test_input_dropdown_lists_devices_and_does_not_switch_motion_on_hotplug(names, label):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script(PAD)

            async def route(request):
                path = request.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    await request.fulfill(body="<main></main>", content_type="text/html")
                else:
                    await request.fulfill(path=STATIC / path)

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.evaluate(
                """async names => {
                const {gamepadInput}=await import('/gamepad.js');
                pad.id=names[0];
                window.other={...structuredClone(pad),index:1,id:names[1]};
                navigator.getGamepads=()=>[pad,other].filter(p=>p.connected);
                window.sent=0;window.stopped=0;
                window.input=gamepadInput({name:'MIRA',controls:{groups:{left:4,right:4}}},
                    async()=>{sent++},async()=>{stopped++});
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""",
                names,
            )
            selector = page.get_by_label("MIRA input", exact=True)
            await expect(selector.locator("option")).to_have_text(
                ["Keyboard", f"{label} · 1", f"{label} · 2"]
            )
            await selector.select_option("1")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate("pad.connected=false")
            await expect(selector.locator("option")).to_have_text(["Keyboard", label])
            await expect(selector).to_have_value("1")
            await page.evaluate("pad.connected=true")
            await expect(selector.locator("option")).to_have_text(
                ["Keyboard", f"{label} · 1", f"{label} · 2"]
            )
            await expect(selector).to_have_value("1")
            await page.evaluate("other.buttons[4].pressed=true;other.axes[0]=1")
            await page.wait_for_function("sent>0")
            # A different controller reusing the same browser index must not inherit control.
            await page.evaluate("other.id='Replacement controller'")
            await expect(selector).to_have_value("keyboard")
            await page.wait_for_function("stopped>0")
            count = await page.evaluate("sent")
            await page.wait_for_timeout(150)
            assert await page.evaluate("sent") == count
            await expect(selector.locator("option")).to_have_text(
                ["Keyboard", label, "Replacement controller"]
            )
            # A missing duplicate must not restore a different pad or auto-select on reconnect.
            await page.evaluate(
                "selection=>input.restore(selection)", {"name": label, "ordinal": 1, "count": 2}
            )
            await page.wait_for_timeout(100)
            await expect(selector).to_have_value("keyboard")
            await page.evaluate("other.id=pad.id")
            await expect(selector.locator("option")).to_have_text(
                ["Keyboard", f"{label} · 1", f"{label} · 2"]
            )
            await expect(selector).to_have_value("keyboard")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_gamepad_controls_only_one_robot_at_a_time():
    robots = [
        {
            "id": name,
            "name": name,
            "kind": "mira-sim",
            "controls": {"inputs": ["buttons", "gamepad"], "groups": {"left": 4, "right": 4}},
            "status": "online",
        }
        for name in ("First", "Second")
    ]
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "session": {
            "id": "one",
            "status": "approved",
            "robot": True,
            "robots": robots,
            "cameras": [],
        },
    }
    actions = []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            call = json.loads(request.request.post_data)
            if call["action"] != "robot.renew":
                actions.append(call)
            await request.fulfill(json={"result": True})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script(PAD)
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await page.get_by_label("First input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
            for _ in range(40):
                if any(a["action"] == "robot.move" for a in actions):
                    break
                await page.wait_for_timeout(50)
            await page.locator("#robot-selector").select_option("Second")
            await page.get_by_role("button", name="Release control and switch", exact=True).click()
            await expect(page.get_by_label("Second input", exact=True)).to_have_value("0")
            assert actions[-1]["action"] == "robot.release"
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            await page.evaluate("pad.buttons[4].pressed=false;pad.axes.fill(0)")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            actions.clear()
            await expect(page.locator(".gamepad-controls:visible")).to_have_attribute(
                "data-state", "ready"
            )
            await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
            for _ in range(40):
                if any(a["action"] == "robot.move" for a in actions):
                    break
                await page.wait_for_timeout(50)
            moves = [a for a in actions if a["action"] == "robot.move"]
            assert moves and {a["params"]["id"] for a in moves} == {"Second"}
            await page.evaluate("document.hasFocus=()=>false")
            await expect(page.locator(".gamepad-controls:visible")).to_have_attribute(
                "data-state", "paused"
            )
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            assert actions[-1]["action"] == "robot.hold"
            await page.get_by_label("Second input", exact=True).select_option("keyboard")
            await page.locator("#robot-selector").select_option("First")
            await page.get_by_role("button", name="Release control and switch", exact=True).click()
            # Preferences belong to each robot; Second's keyboard choice must not
            # overwrite First's gamepad choice or resume First's released control.
            await expect(page.get_by_label("First input", exact=True)).to_have_value("0")
            await expect(
                page.get_by_role("button", name="Acquire control", exact=True)
            ).to_be_visible()
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["deadman", "disconnect", "blur", "permission"])
async def test_grippers_share_deadman_and_stop_independently(ending):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script(PAD)

            async def route(request):
                path = request.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    await request.fulfill(body="<main></main>", content_type="text/html")
                else:
                    await request.fulfill(path=STATIC / path)

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.evaluate("""async () => {
                const {gamepadInput}=await import('/gamepad.js');
                window.moves=[];window.stops=0;
                window.input=gamepadInput({name:'MIRA',controls:{
                    groups:{left:5,right:5},grippers:['left','right']}},
                    async(command,mode)=>{moves.push({command,mode})},async()=>{stops++},
                    ()=>1,()=>30);
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""")
            await page.get_by_label("MIRA input", exact=True).select_option("0")
            # A held gripper button must not arm when the enable button is pressed.
            await page.evaluate("pad.buttons[14].pressed=true")
            await expect(page.locator(".gamepad-status")).to_contain_text("release gripper")
            await page.evaluate("pad.buttons[4].pressed=true")
            await expect(page.locator(".gamepad-status")).to_contain_text("Release")
            assert await page.evaluate("moves.length") == 0
            await page.evaluate("pad.buttons[4].pressed=pad.buttons[14].pressed=false")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            # Simultaneous sticks and both grippers use independent directions and speed.
            await page.evaluate("""() => {
                pad.buttons[4].pressed=pad.buttons[14].pressed=pad.buttons[1].pressed=true;
                pad.axes=[1,0,0,-1];
            }""")
            await page.wait_for_function(
                "moves.some(m=>m.mode==='jog') && moves.some(m=>m.mode==='grip')"
            )
            assert await page.evaluate("moves.find(m=>m.mode==='grip').command") == {
                "velocity": {"left": -0.3, "right": 0.3}
            }
            assert await page.evaluate("moves.find(m=>m.mode==='jog').command") == {
                "left": [1, 0, 0, 0, 0],
                "right": [0, 1, 0, 0, 0],
            }
            # Releasing one gripper explicitly zeros it while the other inputs continue.
            await page.evaluate("moves=[];pad.buttons[14].pressed=false")
            await page.wait_for_function(
                "moves.some(m=>m.mode==='grip' && m.command.velocity.left===0)"
            )
            assert (
                await page.evaluate("moves.find(m=>m.mode==='grip').command.velocity.right") == 0.3
            )
            # Opposing right-gripper buttons cancel without releasing the moving arms.
            await page.evaluate("moves=[];pad.buttons[2].pressed=true")
            await page.wait_for_function(
                "moves.some(m=>m.mode==='grip' && m.command.velocity.right===0)"
            )
            assert await page.evaluate("stops") == 0
            await page.evaluate(
                "pad.buttons[1].pressed=false;pad.buttons[15].pressed=true;moves=[]"
            )
            await page.wait_for_function(
                "moves.some(m=>m.mode==='grip' && m.command.velocity.left===0.3 "
                "&& m.command.velocity.right===-0.3)"
            )
            # Centering sticks sends a zero joint command while grippers keep moving.
            await page.evaluate("moves=[];pad.axes.fill(0)")
            await page.wait_for_function(
                "moves.some(m=>m.mode==='jog' && Object.values(m.command).flat().every(v=>v===0))"
            )
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
            await page.wait_for_timeout(180)
            assert await page.evaluate("moves.length") == count
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_slow_gripper_command_does_not_queue_arm_motion_after_release():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script(PAD)

            async def route(request):
                path = request.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    await request.fulfill(body="<main></main>", content_type="text/html")
                else:
                    await request.fulfill(path=STATIC / path)

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.evaluate("""async () => {
                const {gamepadInput}=await import('/gamepad.js');
                window.moves=[];window.stops=0;
                window.input=gamepadInput({name:'MIRA',controls:{
                    groups:{left:5,right:5},grippers:['left','right']}},
                    (command,mode)=>{moves.push({command,mode});
                        return new Promise(r=>window.reply=r)},
                    async()=>{stops++});
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""")
            await page.get_by_label("MIRA input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-controls")).to_have_attribute("data-state", "ready")
            await page.evaluate("pad.buttons[4].pressed=pad.buttons[14].pressed=true;pad.axes[0]=1")
            await page.wait_for_function("moves.length===1")
            assert await page.evaluate("moves[0].mode") == "grip"
            await page.evaluate("pad.buttons[4].pressed=false")
            await page.wait_for_function("stops===1")
            await page.evaluate("reply()")
            await page.wait_for_timeout(180)
            assert await page.evaluate("moves.length") == 1
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()
