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
            actions.append(json.loads(request.request.post_data))
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
            await page.get_by_label("Robot input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
            # Sticks do not move without the deadman; small drift stays in the dead zone.
            await page.evaluate("pad.axes[0]=0.5")
            await page.wait_for_timeout(150)
            assert not [a for a in actions if a["action"] == "robot.move"]
            await page.evaluate("pad.axes[0]=0.1")
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
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
            command = moves[-1]["params"]["command"]
            key = next(iter(groups))
            assert command[key][0] == pytest.approx(0.2)
            assert sum(v != 0 for values in command.values() for v in values) == 1
            assert len(command[key]) == groups[key]
            if "left" in groups:
                await expect(page.get_by_label("Robot gamepad joints")).to_be_hidden()
                await page.evaluate("pad.axes[2]=-0.575")
                await page.wait_for_timeout(160)
                command = [a for a in actions if a["action"] == "robot.move"][-1]["params"][
                    "command"
                ]
                assert command["left"] == pytest.approx([0.2, 0, 0, 0])
                assert command["right"] == pytest.approx([-0.1, 0, 0, 0])
                # Changing joint pairs stops both arms and requires a fresh deadman press.
                await page.evaluate("pad.buttons[5].pressed=true")
                await expect(page.locator(".gamepad-status")).to_contain_text("Release")
                assert actions[-1]["action"] == "robot.release"
                count = len([a for a in actions if a["action"] == "robot.move"])
                await page.wait_for_timeout(150)
                assert len([a for a in actions if a["action"] == "robot.move"]) == count
                await page.evaluate("pad.buttons[4].pressed=false;pad.axes.fill(0)")
                await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
                await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=0.575;pad.axes[3]=-1")
                await page.wait_for_timeout(160)
                command = [a for a in actions if a["action"] == "robot.move"][-1]["params"][
                    "command"
                ]
                assert command["left"] == pytest.approx([0, 0, 0.1, 0])
                assert command["right"] == pytest.approx([0, 0, 0, 0.2])
                await page.evaluate(
                    "pad.buttons[4].pressed=false;pad.buttons[5].pressed=false;pad.axes.fill(0)"
                )
                await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
                await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
                await page.wait_for_timeout(100)
            # Changing the shared step stops active input; a held deadman cannot
            # silently resume at the new scale after editing the number field.
            step = page.get_by_label("Robot joint step", exact=True)
            await step.fill("0.37")
            await step.press("Enter")
            await expect(page.locator(".gamepad-status")).to_contain_text("Release")
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            assert actions[-1]["action"] == "robot.release"
            await page.evaluate("pad.buttons[4].pressed=false; pad.axes.fill(0)")
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
            await page.evaluate("pad.buttons[4].pressed=true; pad.axes[0]=-0.575")
            for _ in range(40):
                if len([a for a in actions if a["action"] == "robot.move"]) > count:
                    break
                await page.wait_for_timeout(50)
            moves = [a for a in actions if a["action"] == "robot.move"]
            assert len(moves) > count
            assert moves[-1]["params"]["command"][key][0] == pytest.approx(-0.185)
            # Releasing cancels motion and releases the remote lock.
            await page.evaluate("pad.buttons[4].pressed=false; pad.axes.fill(0)")
            for _ in range(40):
                if actions[-1]["action"] == "robot.release":
                    break
                await page.wait_for_timeout(50)
            assert actions[-1]["action"] == "robot.release"
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
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
            # Permission loss while moving also releases control.
            await page.evaluate("pad.buttons[4].pressed=false; pad.axes.fill(0)")
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
            await page.evaluate("pad.buttons[4].pressed=true; pad.axes[0]=1")
            for _ in range(40):
                if len([a for a in actions if a["action"] == "robot.move"]) > count:
                    break
                await page.wait_for_timeout(50)
            releases = len([a for a in actions if a["action"] == "robot.release"])
            state["session"]["robot"] = False
            await expect(page.locator("#robots-panel")).to_contain_text("View-only access")
            await expect(page.locator("#robots .gamepad-controls")).to_have_count(0)
            for _ in range(40):
                if len([a for a in actions if a["action"] == "robot.release"]) > releases:
                    break
                await page.wait_for_timeout(50)
            assert len([a for a in actions if a["action"] == "robot.release"]) > releases
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
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
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
async def test_input_dropdown_lists_devices_and_does_not_switch_motion_on_hotplug():
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
                window.other={...structuredClone(pad),index:1,id:'DualSense'};
                navigator.getGamepads=()=>[pad,other].filter(p=>p.connected);
                window.sent=0;window.stopped=0;
                const input=gamepadInput({name:'MIRA',controls:{groups:{left:4,right:4}}},
                    async()=>{sent++},async()=>{stopped++});
                document.querySelector('main').append(input.select,input.element);
                input.update(true,true);
            }""")
            selector = page.get_by_label("MIRA input", exact=True)
            await expect(selector.locator("option")).to_have_text(
                ["Keyboard", "Test standard gamepad", "DualSense"]
            )
            await selector.select_option("1")
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
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
                ["Keyboard", "Test standard gamepad", "Replacement controller"]
            )
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
            actions.append(json.loads(request.request.post_data))
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
            await page.get_by_label("First input", exact=True).select_option("0")
            await expect(page.locator(".gamepad-status")).to_contain_text("Ready")
            await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
            for _ in range(40):
                if any(a["action"] == "robot.move" for a in actions):
                    break
                await page.wait_for_timeout(50)
            await page.locator("#robot-selector").select_option("Second")
            await expect(page.get_by_label("Second input", exact=True)).to_have_value("keyboard")
            assert actions[-1]["action"] == "robot.release"
            await page.evaluate("pad.buttons[4].pressed=false;pad.axes.fill(0)")
            await page.get_by_label("Second input", exact=True).select_option("0")
            actions.clear()
            await expect(page.locator(".gamepad-controls:visible .gamepad-status")).to_contain_text(
                "Ready"
            )
            await page.evaluate("pad.buttons[4].pressed=true;pad.axes[0]=1")
            for _ in range(40):
                if any(a["action"] == "robot.move" for a in actions):
                    break
                await page.wait_for_timeout(50)
            moves = [a for a in actions if a["action"] == "robot.move"]
            assert moves and {a["params"]["id"] for a in moves} == {"Second"}
            await page.evaluate("document.hasFocus=()=>false")
            await expect(page.locator(".gamepad-controls:visible .gamepad-status")).to_contain_text(
                "paused"
            )
            count = len([a for a in actions if a["action"] == "robot.move"])
            await page.wait_for_timeout(150)
            assert len([a for a in actions if a["action"] == "robot.move"]) == count
            assert actions[-1]["action"] == "robot.release"
        finally:
            await browser.close()
