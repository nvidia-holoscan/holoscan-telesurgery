# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay visibility and Stop use the same dashboard ownership and input gates."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import (
    FrankaSimulation,
    MiraSimulation,
    VersiusSimulation,
)

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("device", ["keyboard", "gamepad", "haply"])
@pytest.mark.parametrize("ending", ["escape", "complete", "blur", "hidden", "error", "stall"])
@pytest.mark.parametrize(
    "environment,name,adapter,width",
    [
        ("franka", "Franka", FrankaSimulation, 1280),
        ("versius", "Versius left", VersiusSimulation, 1280),
        ("mira", "MIRA", MiraSimulation, 1280),
        ("mira", "MIRA", MiraSimulation, 360),
    ],
)
async def test_replay_requires_matching_recording_and_ownership_and_escape_discards_reply(
    environment, name, adapter, width, ending, device, tmp_path
):
    role = "left" if environment == "versius" else environment
    simulated = adapter({"uri": "unused"})
    if environment == "franka":
        simulated.grippers = ("hand",)
    robot = {
        "id": f"node:{role}",
        "name": name,
        "kind": f"{environment}-sim",
        "simulation": True,
        "status": "online",
        "state": {"sequence": 1},
        "controls": controls(simulated, {"motion_enabled": True}),
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "haply_available": True,
        "selected": [],
        "native_views": {},
        "native_controller": {"status": "closed"},
        "replays": [],
        "session": {
            "id": "X",
            "name": "X",
            "status": "approved",
            "robot": True,
            "robots": [robot],
            "cameras": [],
        },
    }
    calls, errors = [], []
    gate, reading = asyncio.Event(), asyncio.Event()
    move_gate = asyncio.Event()

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            body = request.request.post_data_json
            calls.append(body)
            method = body["action"]
            if method == "replay.read":
                reading.set()
                await gate.wait()
                if ending == "error":
                    await request.fulfill(
                        status=400, json={"error": "Measured feedback unavailable"}
                    )
                    return
                result = {
                    "request": None
                    if ending == "complete"
                    else ["jog", {"translation": [1, 0, 0], "rotation": [0, 0, 0]}],
                    "speed_deg_s": 3,
                    "elapsed": 0.1,
                    "done": ending == "complete",
                    "feedback_paced": True,
                    "input": {
                        "device": device,
                        "keys": ["w", "z"],
                        "axes": [1, 0, 0, 0],
                        "buttons": [4, 3, 2],
                    },
                }
            elif method.startswith("replay."):
                result = True
            else:
                if method == "robot.move" and ending == "blur":
                    await move_gate.wait()
                    await request.fulfill(status=400, json={"error": "Replay stopped"})
                    return
                if method == "robot.acquire":
                    robot.update(owner="X", owner_id="X")
                if method == "robot.release":
                    robot.update(owner=None, owner_id=None)
                robot["state"]["sequence"] += 1
                result = robot["state"]
            await request.fulfill(json={"result": result})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                bypass_csp=True, viewport={"width": width, "height": 900}
            )
            await context.add_init_script(
                "document.hasFocus = () => true; navigator.getGamepads = () => [{"
                "id:'Test standard gamepad', index:0, mapping:'standard', connected:true,"
                "axes:[0,0,0,0], buttons:Array.from({length:17},()=>({pressed:false,value:0}))}];"
            )
            await context.route("http://localhost:8777/**", route)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            # CI scheduling must not impersonate a stalled input timer.
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.goto("http://localhost:8777/")
            control = page.get_by_role("button", name="Replay inputs", exact=True)
            await expect(control).to_be_hidden()
            state["replays"] = [
                {
                    "id": f"{environment}/{device}",
                    "environment": environment,
                    "device": device,
                    "task": "Scan",
                    "streams": [role],
                }
            ]
            await page.clock.run_for(1100)
            await expect(control).to_be_hidden()
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            selector = page.get_by_label(f"{name} input", exact=True)
            await selector.select_option("0" if device == "gamepad" else device)
            # Replay availability updates on the next dashboard refresh. Do not
            # depend on acquisition's response still being in flight at selection.
            await page.clock.run_for(1000)
            await expect(control).to_be_visible()
            async with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/action")
                    and response.request.post_data_json["action"] == "replay.start"
                )
            ):
                await control.click()
            await page.clock.run_for(50)
            await asyncio.wait_for(reading.wait(), 3)
            selector = page.get_by_label(f"{name} input", exact=True)
            await expect(selector).to_be_disabled()
            toolbar = await page.locator(".robot-toolbar").bounding_box()
            message = await page.locator(".replay-status").bounding_box()
            assert message["y"] >= toolbar["y"] + toolbar["height"]
            assert (await selector.bounding_box())["width"] >= 120
            assert await page.locator(".robot-toolbar").evaluate(
                "e => e.scrollWidth <= e.clientWidth"
            )
            await page.locator("#robots-panel").screenshot(path=str(tmp_path / "replay-layout.png"))
            await page.clock.run_for(250)
            assert any(c["action"] == "replay.heartbeat" for c in calls)
            if ending == "escape":
                await page.keyboard.press("Escape")
            elif ending == "blur":
                await page.evaluate(
                    "document.hasFocus = () => false; window.dispatchEvent(new Event('blur'))"
                )
                gate.set()
                await page.clock.run_for(250)
                assert any(c["action"] == "robot.move" for c in calls)
                assert not any(c["action"] == "replay.cancel" for c in calls)
                assert not any(c["action"] == "robot.hold" for c in calls)
                if device == "keyboard":
                    await expect(page.locator('.key-cap[data-key="w"]')).to_have_attribute(
                        "data-pressed", "true"
                    )
                elif device == "gamepad":
                    assert await page.locator('.gamepad-controls [data-active="true"]').count() > 0
                if device in {"keyboard", "gamepad"}:
                    assert await page.locator(
                        '.gripper-controls [data-pressed="true"], '
                        '.gripper-controls [data-active="true"]'
                    ).count() > 0
                    await page.get_by_label("Color theme").select_option("dark")
                    await page.locator("#robots-panel").screenshot(
                        path=str(tmp_path / "replay-active-dark.png")
                    )
                await expect(selector).to_be_disabled()
                await page.evaluate("document.hasFocus = () => true")
                await page.keyboard.press("Escape")
                move_gate.set()
            elif ending == "stall":
                await page.clock.fast_forward(250)
            elif ending == "hidden":
                await page.evaluate(
                    "Object.defineProperty(document, 'hidden', {value: true, configurable: true});"
                    "document.dispatchEvent(new Event('visibilitychange'))"
                )
            gate.set()
            await page.clock.run_for(250)
            assert any(c["action"] == "replay.cancel" for c in calls) == (ending != "complete")
            if ending == "complete":
                await expect(page.locator(".replay-status")).to_have_text("Replay complete")
            else:
                reason = (
                    "dashboard timer delayed"
                    if ending == "stall"
                    else "dashboard hidden"
                    if ending == "hidden"
                    else "Measured feedback unavailable"
                    if ending == "error"
                    else "Escape pressed"
                )
                await expect(page.locator(".replay-status")).to_have_text(
                    f"Replay stopped · {reason}"
                )
            if ending != "blur":
                assert not any(c["action"] == "robot.move" for c in calls)
            else:
                stopped = sum(c["action"] == "robot.move" for c in calls)
                await page.clock.run_for(150)
                assert sum(c["action"] == "robot.move" for c in calls) == stopped
                await expect(page.locator("#notice")).to_be_hidden()
            await expect(selector).to_be_enabled()
            await page.clock.run_for(60)
            assert await page.locator('[data-pressed="true"], [data-active="true"]').count() == 0
            await page.get_by_role("button", name="Release control", exact=True).click()
            await expect(control).to_be_hidden()
            assert not errors
        finally:
            gate.set()
            move_gate.set()
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["left", "right"])
async def test_legacy_checkpoint_wait_message_is_displayed(role):
    message = f"Waiting for the {'right' if role == 'left' else 'left'} arm checkpoint"
    done = False

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/action":
            result = (
                {
                    "request": None,
                    "feedback_paced": True,
                    "waiting_peer": True,
                    "waiting_reason": message,
                    "done": done,
                    "elapsed": 0,
                }
                if request.request.post_data_json["action"] == "replay.read"
                else True
            )
            await request.fulfill(json={"result": result})
        elif path == "/":
            await request.fulfill(
                content_type="text/html",
                body="""<script type="module">
                    import {replayControls} from './static/replay.js';
                    const role = new URLSearchParams(location.search).get('role');
                    const controls = replayControls(
                        {id:'node:'+role,kind:'versius-sim',simulation:true},
                        async()=>{}, async()=>{throw Error('Unexpected motion')},
                        async()=>{}, async()=>{}, ()=>{});
                    controls.update([{id:'versius/gamepad',environment:'versius',
                        device:'gamepad',streams:[role],task:'Handoff'}], 'gamepad', true);
                    document.body.append(controls.button, controls.status);
                </script>""",
            )
        else:
            await request.fulfill(path=STATIC / path.removeprefix("/static/"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            await context.add_init_script("document.hasFocus = () => true")
            await context.route("http://localhost:8777/**", route)
            page = await context.new_page()
            await page.goto(f"http://localhost:8777/?role={role}")
            await page.get_by_role("button", name="Replay inputs", exact=True).click()
            await expect(page.locator(".replay-status")).to_have_text(message)
            done = True
            await expect(page.locator(".replay-status")).to_have_text("Replay complete")
        finally:
            await browser.close()
