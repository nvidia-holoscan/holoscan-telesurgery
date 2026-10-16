# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Keyboard input uses the shared joint pipeline and never resumes interrupted motion."""

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["mira", "mira-sim", "franka-sim", "franka"])
async def test_keyboard_mapping_permission_and_robot_switch(kind, tmp_path):
    groups = {"joints": 7} if kind.startswith("franka") else {"left": 4, "right": 4}
    robot = {
        "id": "host:robot",
        "name": "Robot",
        "kind": kind,
        "status": "online",
        "simulation": kind.endswith("-sim"),
        "stale": False,
        "controls": {
            "inputs": ["buttons", "keyboard", "gamepad"],
            "groups": groups,
            "step_deg": 0.4,
        },
        "state": {
            "joints_deg": {key: list(range(7 if key == "joints" else 6)) for key in groups},
            "feedback_source": "test feedback",
        },
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "session": {
            "id": "operator",
            "status": "approved",
            "robot": True,
            "cameras": [],
            "robots": [robot, {**robot, "id": "host:other", "name": "Other"}],
        },
    }
    calls, errors = [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            call = json.loads(request.request.post_data)
            if call["action"] != "robot.renew":
                calls.append(call)
            await request.fulfill(json={"result": True})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("http://localhost:8777/**", route)
            # CI scheduling must not impersonate a stalled input timer.
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.goto("http://localhost:8777/")
            await page.get_by_label("Selected robot").select_option("host:robot")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await page.get_by_label("Robot input", exact=True).select_option("keyboard")
            await expect(page.locator(".keyboard-controls")).to_be_visible()
            await expect(page.locator(".robot-state")).to_be_hidden()
            if kind.startswith("franka"):
                await expect(page.locator(".keyboard-columns")).to_contain_text("Measured (°)")
            if not kind.startswith("franka"):
                await expect(page.locator(".joint-position")).to_have_count(8)
                await expect(page.locator(".key-cap")).to_have_count(16)
                await expect(page.locator('.joint-position[data-joint="5"]')).to_have_count(0)
                await expect(page.get_by_label("Robot keyboard joints")).to_be_hidden()
                await expect(page.locator(".keyboard-columns")).to_have_text(
                    ["Left°−+", "Right°−+"]
                )
            await page.keyboard.down("q")
            await page.clock.run_for(160)
            await page.keyboard.up("q")
            await page.clock.run_for(100)
            moves = [c for c in calls if c["action"] == "robot.move"]
            assert len(moves) == 1
            assert moves[0]["params"]["mode"] == "step"
            # Releasing the key does not cancel the accepted fixed target.
            assert all(c["action"] != "robot.release" for c in calls)
            first = "joints" if kind.startswith("franka") else "left"
            for move in moves:
                command = move["params"]["command"]
                assert command[first] == pytest.approx([0.08] + [0] * (groups[first] - 1))
                assert all(
                    v == 0 for key, values in command.items() if key != first for v in values
                )
            await page.keyboard.press("Escape")
            await page.clock.run_for(100)
            assert calls[-1]["action"] == "robot.hold"
            calls.clear()
            if not kind.startswith("franka"):
                await page.keyboard.down("q")
                await page.clock.run_for(80)
                await page.keyboard.down("u")
                await page.clock.run_for(650)
                moves = [c for c in calls if c["action"] == "robot.move"]
                command = moves[-1]["params"]["command"]
                distance = command["left"][0]
                assert 0.076 <= distance <= 0.16
                assert command == {"left": [distance, 0, 0, 0], "right": [distance, 0, 0, 0]}
                await page.keyboard.up("q")
                await page.clock.run_for(150)
                moves = [c for c in calls if c["action"] == "robot.move"]
                command = moves[-1]["params"]["command"]
                assert 0.076 <= command["right"][0] <= 0.16
                assert command == {
                    "left": [0, 0, 0, 0],
                    "right": [command["right"][0], 0, 0, 0],
                }
                await page.keyboard.up("u")
                await page.clock.run_for(150)
                assert calls[-1]["action"] == "robot.hold"
                calls.clear()
            # Older nodes advertise only step_deg; their limit still applies.
            setting = "arm speed"
            step = page.get_by_label(f"Robot {setting}", exact=True)
            await expect(step).to_have_attribute("max", "100")
            await step.focus()
            await step.press("End")
            distance = 0.4
            await step.press("Enter")
            if not kind.startswith("franka"):
                robot["state"]["joints_deg"]["right"][3] = 12.34
                await page.clock.run_for(1000)
                await expect(
                    page.locator('.joint-position[data-group="right"][data-joint="3"]')
                ).to_have_text("12.34")
                # Vendor-only fields do not grant a movement binding.
                await page.keyboard.press("t")
                assert not [c for c in calls if c["action"] == "robot.move"]
            await page.keyboard.down("j" if kind.startswith("franka") else ";")
            await page.clock.run_for(130)
            await page.keyboard.press("Escape")
            await page.keyboard.up("j" if kind.startswith("franka") else ";")
            await page.clock.run_for(100)
            moves = [c for c in calls if c["action"] == "robot.move"]
            assert len(moves) == 1
            key, count = ("joints", 7) if kind.startswith("franka") else ("right", 4)
            assert all(
                c["params"]["command"][key] == [0] * (count - 1) + [-distance] for c in moves
            )
            assert calls[-1]["action"] == "robot.hold"
            await page.screenshot(path=str(tmp_path / f"{kind}-keyboard.png"))
            calls.clear()
            # Input listeners are removed when switching robots. Held keys cannot
            # transfer to a different robot or resume after an approval changes.
            await page.keyboard.down("q")
            await page.clock.run_for(80)
            await page.get_by_label("Selected robot").select_option("host:other")
            await page.get_by_role("button", name="Release control and switch", exact=True).click()
            await page.clock.run_for(100)
            assert all(c["params"]["id"] == "host:robot" for c in calls)
            await page.keyboard.up("q")
            await expect(page.get_by_label(f"Other {setting}", exact=True)).to_have_value("20")
            await page.get_by_label("Selected robot").select_option("host:robot")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await expect(page.get_by_label(f"Robot {setting}", exact=True)).to_have_value("100")
            await expect(page.get_by_role("button", name="Stop", exact=True)).to_be_enabled()
            await page.locator(".keyboard-controls").focus()
            # Each joint keeps producing fresh jogs without OS key-repeat events.
            # Both robot types use this behavior on physical and simulated nodes.
            negative_keys = "asdfghj" if kind.startswith("franka") else "asdfjkl;"
            for index, key in enumerate(negative_keys):
                calls.clear()
                await page.keyboard.down(key)
                await page.clock.run_for(700)
                await page.keyboard.up(key)
                await page.clock.run_for(100)
                moves = [c for c in calls if c["action"] == "robot.move"]
                assert len(moves) >= 3
                assert moves[0]["params"]["mode"] == "step"
                assert all(c["params"]["mode"] == "jog" for c in moves[1:])
                expected = {group: [0] * count for group, count in groups.items()}
                group = (
                    "joints" if kind.startswith("franka") else ("left" if index < 4 else "right")
                )
                expected[group][index if group == "joints" else index % 4] = -distance
                for move in moves:
                    for name, values in expected.items():
                        assert move["params"]["command"][name] == pytest.approx(values, abs=0.008)
                assert calls[-1]["action"] == "robot.hold"
                await page.clock.run_for(100)
                assert len([c for c in calls if c["action"] == "robot.move"]) == len(moves)
            state["session"]["robot"] = False
            await page.clock.run_for(1000)
            await expect(page.locator("#robots")).to_contain_text("View-only access")
            await expect(page.locator(".keyboard-controls")).to_have_count(0)
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interruption", ["blur", "dialog", "metrics", "field", "step", "permission", "delayed"]
)
async def test_keyboard_interruptions_never_replay_slow_commands(interruption):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            async def route(request):
                path = request.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    await request.fulfill(
                        body='<main></main><input id="field"><dialog>Dialog</dialog>'
                        '<aside role="dialog" hidden></aside>',
                        content_type="text/html",
                    )
                else:
                    await request.fulfill(path=STATIC / path)

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.evaluate("""async () => {
                const {keyboardInput} = await import('/keyboard.js');
                const {jointStep} = await import('/robot-input.js');
                const robot={id:'test',name:'MIRA',controls:{groups:{left:4,right:4}}};
                window.sent=0;window.stopped=0;
                const step=jointStep(robot, () => input.stop());
                window.input=keyboardInput(robot,
                  () => {sent++;return new Promise(resolve => window.reply=resolve)},
                  async () => {stopped++}, step.value);
                document.querySelector('main').append(step.element,input.element);
                input.update(true,true);
            }""")
            await page.keyboard.down("q")
            await page.wait_for_function("sent===1")
            await page.evaluate(
                {
                    "blur": "window.dispatchEvent(new Event('blur'))",
                    "dialog": "document.querySelector('dialog').showModal()",
                    "metrics": "() => {const d=document.querySelector('aside');"
                    "d.hidden=false;d.setAttribute('aria-modal','true')}",
                    "field": "document.querySelector('#field').focus()",
                    "step": "() => {const s=document.querySelector('.motion-value input');"
                    "s.value='0.05';s.dispatchEvent(new Event('input'))}",
                    "permission": "input.update(true,false)",
                    "delayed": "() => {const start=performance.now();"
                    "while(performance.now()-start<250){}}",
                }[interruption]
            )
            await page.wait_for_function("stopped===1")
            await page.evaluate("""() => {
                document.querySelector('dialog').close();document.querySelector('aside').hidden=true;
                document.querySelector('.keyboard-controls').focus();input.update(true,true);reply();
            }""")
            # Browsers send repeated keydown events for held keys after returning.
            await page.keyboard.down("q")
            await page.wait_for_timeout(150)
            assert await page.evaluate("sent") == 1
            await page.keyboard.up("q")
            await page.keyboard.down("a")
            await page.wait_for_function("sent===2")
            # Releasing and re-pressing during the pending command is not queued.
            await page.keyboard.up("a")
            await page.keyboard.down("q")
            await page.evaluate("reply()")
            await page.wait_for_timeout(150)
            assert await page.evaluate("sent") == 2
            await page.keyboard.up("q")
            await page.evaluate("input.destroy()")
        finally:
            await browser.close()
