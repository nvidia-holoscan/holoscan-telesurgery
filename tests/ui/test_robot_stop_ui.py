# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A stop acknowledgement must block input before slower inventory polling catches up."""

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"


@pytest.mark.asyncio
@pytest.mark.parametrize("hold_fails", [False, True])
async def test_rejected_move_holds_control_unless_stop_also_fails(hold_fails):
    robot = {
        "id": "node:franka",
        "name": "Franka",
        "kind": "franka-sim",
        "status": "online",
        "simulation": True,
        "stale": False,
        "controls": {"groups": {"joints": 7}, "step_deg": 1},
        "state": {"sequence": 1, "control_active": False, "joints_deg": {"joints": [0] * 7}},
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
            "robots": [robot],
        },
    }
    calls = []

    async def route(route):
        path = route.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await route.fulfill(json=state)
        elif path == "api/action":
            method = route.request.post_data_json["action"]
            calls.append(method)
            if method == "robot.move" or (method == "robot.hold" and hold_fails):
                await route.fulfill(status=409, json={"error": "Controller rejected request"})
            else:
                await route.fulfill(
                    json={"result": {"sequence": len(calls) + 1, "control_active": False}}
                )
        else:
            await route.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            key = page.locator('.key-cap[data-key="g"]')
            await expect(key).to_be_enabled()
            await key.hover()
            await page.mouse.down()
            for _ in range(120):
                if "robot.hold" in calls and (not hold_fails or "robot.release" in calls):
                    break
                await page.wait_for_timeout(25)
            assert "robot.hold" in calls, calls
            await page.wait_for_timeout(300)
            assert calls.count("robot.move") == 1  # Never replay the held key after rejection.
            assert ("robot.release" in calls) == hold_fails
            release = page.get_by_role("button", name="Release control", exact=True)
            if hold_fails:
                await expect(release).to_be_hidden()
            else:
                await expect(release).to_be_visible()
            await page.mouse.up()
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_stop_acknowledgement_blocks_repress_with_stale_inventory():
    robot = {
        "id": "node:franka",
        "name": "Franka",
        "kind": "franka-sim",
        "status": "online",
        "simulation": True,
        "stale": False,
        "controls": {"groups": {"joints": 7}, "step_deg": 1, "default_step_deg": 1},
        "state": {"sequence": 1, "control_active": False, "joints_deg": {"joints": [0] * 7}},
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
            "robots": [robot],
        },
    }
    moves = []
    stopped = asyncio.Event()

    async def route(route):
        path = route.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await route.fulfill(json=state)
        elif path == "api/action":
            call = route.request.post_data_json
            result = True
            if call["action"] == "robot.move":
                moves.append(call)
                result = {"sequence": len(moves) + 1, "control_active": True}
            elif call["action"] == "robot.hold" and moves:
                result = {"sequence": 100, "control_active": True, "stopping": True}
                stopped.set()
            await route.fulfill(json={"result": result})
        else:
            await route.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            key = page.locator('.key-cap[data-key="g"]')
            await expect(key).to_be_enabled()
            position = await key.bounding_box()
            await page.locator(".keyboard-controls").focus()
            await page.keyboard.down("g")
            async with asyncio.timeout(3):
                while len(moves) < 3:
                    await page.wait_for_timeout(25)
            await page.keyboard.up("g")
            await asyncio.wait_for(stopped.wait(), 2)
            await expect(key).to_be_disabled()
            assert await key.bounding_box() == position
            count = len(moves)
            # Polls still return the pre-stop state. A held new key must neither
            # bypass braking nor be queued to run when braking completes.
            await page.keyboard.down("g")
            await page.wait_for_timeout(1100)
            assert len(moves) == count
            await expect(key).to_be_disabled()
            robot["state"] = {"sequence": 101, "control_active": False, "stopping": False}
            await expect(key).to_be_enabled()
            await page.wait_for_timeout(600)
            assert len(moves) == count
            await page.keyboard.up("g")
            await page.wait_for_timeout(20)
            await page.keyboard.press("g")
            async with asyncio.timeout(2):
                while len(moves) == count:
                    await page.wait_for_timeout(25)
            assert len(moves) == count + 1
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_stop_completion_refreshes_controls_without_replaying_held_input():
    moves = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            async def route(route):
                path = route.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    markup = (
                        (STATIC / "index.html")
                        .read_text()
                        .replace('<script type="module" src="/static/app.js"></script>', "")
                    )
                    await route.fulfill(body=markup, content_type="text/html")
                elif path == "api/action":
                    stopped = route.request.post_data_json["action"] == "robot.hold"
                    if route.request.post_data_json["action"] == "robot.move":
                        moves.append(route.request.post_data_json)
                    await route.fulfill(
                        json={
                            "result": {
                                "sequence": 3 if stopped else 2,
                                "stopping": stopped,
                                "grippers": {"hand": 0.25},
                            }
                        }
                    )
                else:
                    await route.fulfill(path=STATIC / path.removeprefix("static/"))

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.evaluate(
                """async () => {
                document.hasFocus=()=>true;
                document.body.append(document.querySelector('#robots'));
                const {robotControls}=await import('/robots.js');
                window.robot={id:'node:versius',name:'Versius',kind:'versius-sim',
                    status:'online',simulation:true,stale:false,
                    controls:{groups:{joints:8},cartesian:{frame:'base'},grippers:['hand'],
                        grip_speed_pct_s:{min:1,max:50,default:20}},
                    state:{sequence:1,stopping:false,grippers:{hand:0.75}}};
                window.refreshes=0;
                const state={role:'surgeon',session:{id:'surgeon',name:'Operator',
                    status:'approved',robot:true}};
                window.render=()=>controls.update(state,{robots:[robot]});
                window.controls=robotControls(async()=>{
                    refreshes++;controls.update(state,{robots:[robot]});
                },()=>{});
                controls.update(state,{robots:[robot]});
            }"""
            )
            key = page.get_by_role("button", name="Versius Forward (W)", exact=True)
            status = page.locator("#robots .status")
            grip = page.get_by_label("hand gripper measured opening", exact=True)
            await expect(status).to_have_text("Available")
            await expect(grip).to_have_text("75%")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await expect(status).to_have_text("Active · Operator")
            await page.clock.run_for(50)
            await page.locator(".keyboard-controls").focus()
            await expect(key).to_be_enabled()
            async with page.expect_response(
                lambda r: r.request.post_data_json.get("action") == "robot.move"
            ):
                await page.keyboard.down("w")
            await expect(status).to_have_text("Active · Operator")
            await expect(grip).to_have_text("25%")
            # An inventory fetched before acquisition cannot undo the newer
            # ownership or measured gripper feedback from its acknowledgement.
            await page.evaluate("render()")
            await expect(status).to_have_text("Active · Operator")
            await expect(grip).to_have_text("25%")
            await page.evaluate("robot.owner='Operator';robot.owner_id='surgeon'")
            async with page.expect_response(
                lambda r: r.request.post_data_json.get("action") == "robot.hold"
            ):
                await page.keyboard.up("w")
                await page.clock.run_for(20)
            await page.clock.run_for(50)
            await expect(status).to_have_text("Active · Operator")
            await expect(key).to_be_disabled()
            await page.keyboard.down("w")
            await page.clock.run_for(100)
            await expect(key).to_be_disabled()
            await expect(status).to_have_text("Active · Operator")
            await page.evaluate(
                "robot.state={sequence:4,stopping:false,grippers:{hand:0.5}};"
                "robot.owner=robot.owner_id=null"
            )
            await page.clock.run_for(100)
            await expect(key).to_be_enabled()
            await expect(grip).to_have_text("50%")
            count = await page.evaluate("refreshes")
            assert count == 3
            await page.clock.run_for(500)
            assert await page.evaluate("refreshes") == count
            # Input pressed during braking must still require a fresh press.
            assert len(moves) == 1
            await page.keyboard.up("w")
            await page.clock.run_for(20)
            async with page.expect_response(lambda r: r.url.endswith("api/action")):
                await page.keyboard.down("w")
            assert len(moves) == 2
            await page.keyboard.up("w")
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_observing_same_session_ownership_does_not_release_another_tabs_input():
    """Observing ownership must not renew it, send input, or release it on blur."""
    calls = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()

            async def route(route):
                path = route.request.url.removeprefix("http://localhost:8777/")
                if not path:
                    markup = (
                        (STATIC / "index.html")
                        .read_text()
                        .replace('<script type="module" src="/static/app.js"></script>', "")
                    )
                    await route.fulfill(body=markup, content_type="text/html")
                elif path == "api/action":
                    calls.append(route.request.post_data_json)
                    await route.fulfill(json={"result": {"sequence": 3}})
                else:
                    await route.fulfill(path=STATIC / path.removeprefix("static/"))

            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.clock.install(time=1000)
            await page.clock.pause_at(1000)
            await page.evaluate(
                """async () => {
                document.hasFocus=()=>true;
                document.body.append(document.querySelector('#robots'));
                const {robotControls}=await import('/robots.js');
                const robot={id:'node:versius',name:'Versius',kind:'versius-sim',
                    status:'online',simulation:true,owner:'Operator',owner_id:'surgeon',
                    controls:{groups:{joints:8},cartesian:{frame:'base'},grippers:['hand'],
                        grip_speed_pct_s:{min:1,max:50,default:20}},
                    state:{sequence:2,control_active:true,grippers:{hand:0.5}}};
                window.controls=robotControls(()=>{},()=>{});
                controls.update({role:'surgeon',session:{id:'surgeon',name:'Operator',
                    status:'approved',robot:true}},{robots:[robot]});
            }"""
            )
            await expect(page.locator("#robots .status")).to_have_text("Active · Operator")
            await page.clock.run_for(1000)
            assert not calls  # An idle observer cannot renew another tab's lease.
            await page.evaluate(
                "window.dispatchEvent(new Event('blur'));"
                "window.dispatchEvent(new Event('pagehide'))"
            )
            await page.clock.run_for(200)
            assert not calls
            await expect(
                page.get_by_role("button", name="Acquire control", exact=True)
            ).to_be_hidden()
            await expect(
                page.get_by_role("button", name="Release control", exact=True)
            ).to_be_visible()
            await page.keyboard.press("z")
            await page.clock.run_for(100)
            assert not calls
            # The same surgeon may explicitly release their control from this tab.
            await page.get_by_role("button", name="Release control", exact=True).click()
            assert calls[-1]["action"] == "robot.release"
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_explicit_ownership_idle_renewal_release_and_patient_force_release(tmp_path):
    calls = []
    robot = {
        "id": "node:franka",
        "name": "Franka",
        "kind": "franka-sim",
        "status": "online",
        "simulation": True,
        "controls": {"groups": {"joints": 7}, "step_deg": 1},
        "state": {"sequence": 1, "control_active": False},
    }
    state = {
        "role": "surgeon",
        "session": {
            "id": "operator",
            "name": "Operator",
            "robot": True,
            "status": "approved",
        },
    }

    async def route(route):
        path = route.request.url.removeprefix("http://localhost:8777/")
        if not path:
            markup = (
                (STATIC / "index.html")
                .read_text()
                .replace('<script type="module" src="/static/app.js"></script>', "")
            )
            await route.fulfill(body=markup, content_type="text/html")
        elif path == "api/action":
            call = route.request.post_data_json
            calls.append(call["action"])
            if call["action"] == "robot.acquire":
                robot.update(owner="Operator", owner_id="operator")
            elif call["action"] in {"robot.release", "robot.revoke"}:
                robot.update(owner=None, owner_id=None)
            robot["state"]["sequence"] += 1
            await route.fulfill(json={"result": robot["state"]})
        else:
            await route.fulfill(path=STATIC / path.removeprefix("static/"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 440, "height": 900})
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.evaluate(
                """async ({state, robot}) => {
                document.body.append(document.querySelector('#robots'));
                const {robotControls} = await import('/robots.js');
                window.state = state; window.robot = robot;
                window.render = () => controls.update(state, {robots: [robot]});
                window.controls = robotControls(async () => render(), () => {});
                render();
            }""",
                {"state": state, "robot": robot},
            )
            acquire = page.get_by_role("button", name="Acquire control", exact=True)
            release = page.get_by_role("button", name="Release control", exact=True)
            status = page.locator("#robots .status")
            await expect(status).to_have_text("Available")
            await expect(acquire).to_be_visible()
            await expect(release).to_be_hidden()
            await page.keyboard.press("q")
            await page.wait_for_timeout(150)
            assert not calls
            await acquire.click()
            await expect(status).to_have_text("Active · Operator")
            await expect(acquire).to_be_hidden()
            await expect(release).to_be_visible()
            await expect(release.locator("svg")).to_be_visible()
            await expect(release.locator("span")).to_have_class("sr-only")
            await expect(page.locator('.key-cap[data-key="q"]')).to_be_enabled()
            await page.keyboard.down("q")
            await page.wait_for_timeout(650)
            await page.keyboard.press("Escape")
            await page.keyboard.up("q")
            await page.evaluate("window.dispatchEvent(new Event('blur'))")
            await page.wait_for_timeout(1200)
            assert "robot.move" in calls and "robot.hold" in calls
            assert calls.count("robot.renew") >= 2
            assert "robot.release" not in calls
            await expect(status).to_have_text("Active · Operator")
            await page.locator("#robots").screenshot(path=str(tmp_path / "active-controls.png"))
            await release.click()
            await expect(status).to_have_text("Available")
            await expect(release).to_be_hidden()
            await expect(acquire).to_be_visible()
            count = len(calls)
            await page.keyboard.press("q")
            await page.wait_for_timeout(650)
            assert len(calls) == count
            await page.evaluate("robot.owner='Other';robot.owner_id='other';render()")
            await expect(status).to_have_text("Active · Other")
            await expect(release).to_be_hidden()
            await expect(acquire).to_be_hidden()
            await page.evaluate("state.role='patient';render()")
            force = page.get_by_role("button", name="Force release robot control", exact=True)
            await expect(force).to_be_visible()
            await force.click()
            assert calls[-1] == "robot.revoke"
            await page.evaluate("robot.owner=robot.owner_id=null;render()")
            await expect(force).to_be_hidden()
        finally:
            await browser.close()
