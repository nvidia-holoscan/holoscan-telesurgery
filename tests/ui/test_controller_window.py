# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native controls share settings and hand control back to the inline browser panel."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright, expect
from telesurgery_robots.adapters.base import controls
from telesurgery_robots.adapters.simulation import MiraSimulation
from telesurgery_robots.franka.poses import FRANKA_HOME, FRANKA_SPEED

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
INPUT = """
window.inputFocus = true;
document.hasFocus = () => window.inputFocus;
window.pad = {id: 'Test gamepad', index: 0, mapping: 'standard', connected: true,
 axes: [0,0,0,0], buttons: Array.from({length:17}, () => ({pressed:false,value:0}))};
window.other = {...structuredClone(window.pad), index: 1};
navigator.getGamepads = () => [window.pad, window.other].filter(p => p.connected);
window.RTCPeerConnection=class {
 constructor(){this.iceGatheringState='complete'}
 addTransceiver(){return {setCodecPreferences(){}}}
 createDataChannel(){return {readyState:'connecting',bufferedAmount:0,send(){}}}
 async createOffer(){return {type:'offer',sdp:'test'}}
 async setLocalDescription(d){this.localDescription=d}
 async setRemoteDescription(){} close(){} async getStats(){return new Map()}
};
"""


@pytest.mark.asyncio
async def test_robot_switch_cancels_and_waits_for_successful_release():
    robots = [
        {
            "id": str(i),
            "name": f"Arm {i}",
            "kind": "franka",
            "status": "online",
            "controls": {"groups": {"joints": 7}, "step_deg": 0.4},
            "state": {"sequence": 1},
        }
        for i in [1, 2]
    ]
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "native_views": {},
        "session": {
            "id": "operator",
            "status": "approved",
            "robot": True,
            "robots": robots,
            "cameras": [],
        },
    }
    calls = []
    release_started, release_reply = asyncio.Event(), asyncio.Event()
    fail_release = True

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            body = request.request.post_data_json
            calls.append(body)
            robot = next(r for r in robots if r["id"] == body["params"]["id"])
            if body["action"] == "robot.acquire":
                robot.update(owner="Operator", owner_id="operator")
            elif body["action"] == "robot.release":
                release_started.set()
                await release_reply.wait()
                robot.update(owner=None, owner_id=None)
                if fail_release:
                    await request.fulfill(status=409, json={"error": "Stop not confirmed"})
                    return
            robot["state"]["sequence"] += 1
            await request.fulfill(json={"result": robot["state"]})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            picker = page.locator("#robot-selector")
            dialog = page.locator("#switch-robot-dialog")
            await picker.select_option("2")
            await dialog.get_by_role("button", name="Cancel", exact=True).click()
            await expect(picker).to_have_value("1")
            assert not any(c["action"] == "robot.release" for c in calls)
            await picker.select_option("2")
            await dialog.get_by_role(
                "button", name="Release control and switch", exact=True
            ).click()
            await asyncio.wait_for(release_started.wait(), 2)
            await expect(picker).to_be_disabled()
            await expect(picker).to_have_value("1")
            release_reply.set()
            await expect(page.locator("#notice")).to_contain_text("release was not confirmed")
            await expect(picker).to_be_enabled()
            await expect(picker).to_have_value("1")
            fail_release = False
            await picker.select_option("2")
            await dialog.get_by_role(
                "button", name="Release control and switch", exact=True
            ).click()
            await expect(picker).to_have_value("2")
            await expect(
                page.get_by_role("button", name="Acquire control", exact=True)
            ).to_be_visible()
            assert not any(
                c["action"] == "robot.acquire" and c["params"]["id"] == "2" for c in calls
            )
        finally:
            release_reply.set()
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["franka", "mira"])
@pytest.mark.parametrize("selected", ["keyboard", "0", "1"])
async def test_native_controls_handoff_docking_and_startup_failure(kind, selected):
    robot = {
        "id": kind,
        "name": kind.title(),
        "kind": kind,
        "status": "online",
        "controls": controls(MiraSimulation({"uri": "unused"}), {"motion_enabled": True})
        if kind == "mira"
        else {
            "inputs": ["keyboard", "gamepad"],
            "groups": {"joints": 7},
            "max_step_deg": 5,
            "home_deg": {"joints": FRANKA_HOME},
            "speed_deg_s": FRANKA_SPEED,
        },
        "state": {"sequence": 1, "control_active": False},
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": ["first", "second", "existing"],
        "native_views": {"existing": {"status": "running"}},
        "native_controller": {"status": "closed"},
        "session": {
            "id": "operator",
            "name": "Operator",
            "status": "approved",
            "robot": True,
            "robots": [robot],
            "cameras": [
                {
                    "id": key,
                    "name": key,
                    "kind": "fixture",
                    "codec": codec,
                    "width": 1920,
                    "height": 1080,
                    "status": "live",
                }
                for key, codec in [("first", "h264"), ("second", "h265"), ("existing", "bgr8")]
            ],
        },
    }
    calls, errors = [], []
    fail = False

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            call = request.request.post_data_json
            calls.append(call)
            method, params = call["action"], call["params"]
            if method == "controller.open":
                if fail:
                    await request.fulfill(status=409, json={"error": "No desktop display"})
                    return
                state["native_controller"] = {
                    "status": "running",
                    "robot": params["id"],
                    "preferences": params["preferences"],
                    "input": params["input"],
                    "generation": str(len(calls)),
                    "acquired": robot["id"] if params.get("retain_control") else None,
                }
            elif method == "controller.close":
                state["native_controller"]["status"] = "closed"
                robot["state"]["control_active"] = False
            elif method == "robot.move":
                robot.update(owner="Operator", owner_id="operator")
                robot["state"]["control_active"] = True
            elif method == "robot.release":
                robot.update(owner=None, owner_id=None)
                robot["state"]["control_active"] = False
            elif method == "view.holoviz":
                await asyncio.sleep(0.05)  # Controller visibility precedes camera startup.
                state["native_views"][params["camera"]] = {"status": "running"}
            elif method in {"view.browser", "view.close"}:
                state["native_views"].pop(params["camera"], None)
            robot["state"]["sequence"] += 1
            await request.fulfill(
                json={
                    "result": {
                        "robot": state["native_controller"].get("acquired"),
                        "state": robot["state"],
                    }
                    if method == "controller.close" and params.get("retain_control")
                    else robot["state"]
                }
            )
        elif path == "/api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            context = await browser.new_context()
            await context.clock.install(time=1000)
            await context.add_init_script(INPUT)
            await context.route("http://localhost:8777/**", route)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            speed = page.get_by_label(f"{robot['name']} arm speed", exact=True)
            await speed.evaluate("s => {s.value=30;s.dispatchEvent(new Event('input'))}")
            await page.locator(".keyboard-controls").focus()
            await page.keyboard.down("q")
            await context.clock.run_for(650)
            assert any(c["action"] == "robot.move" for c in calls)
            await page.keyboard.up("q")
            selector = page.get_by_label(f"{robot['name']} input", exact=True)
            if selected != "keyboard":
                await selector.select_option(selected)
                await context.clock.run_for(100)
            await page.get_by_role("button", name="Pop out robot controls", exact=True).click()
            await expect(page.locator("#robots")).to_be_hidden()
            await expect(page.locator("#native-controller-away")).to_be_visible()
            assert len(context.pages) == 1
            methods = [c["action"] for c in calls]
            assert "robot.release" not in methods
            assert methods.index("robot.hold") < methods.index("controller.open")
            opened = next(c for c in calls if c["action"] == "controller.open")
            assert opened["params"]["retain_control"] is True
            assert opened["params"]["preferences"][f"{kind}:arm-speed"] == 30
            assert opened["params"]["input"] == (
                None
                if selected == "keyboard"
                else {"name": "Test gamepad", "ordinal": int(selected), "count": 2}
            )
            # Observing the native window's ownership must never release/renew it.
            robot.update(owner="Operator", owner_id="operator")
            state["native_controller"]["preferences"][f"{kind}:arm-speed"] = 55
            count = len([c for c in calls if c["action"].startswith("robot.")])
            await context.clock.run_for(2500)
            assert len([c for c in calls if c["action"].startswith("robot.")]) == count
            await page.keyboard.up("q")
            if selected != "keyboard":
                await page.evaluate(
                    "i => {const p=i===0?pad:other;p.buttons[4].pressed=true;p.axes[0]=1}",
                    int(selected),
                )
            moves = len([c for c in calls if c["action"] == "robot.move"])
            await page.get_by_role("button", name="Dock robot controls", exact=True).click()
            await expect(speed).to_have_value("55")
            await expect(page.locator("#robots")).to_be_visible()
            await expect(selector).to_have_value(selected)
            await expect(
                page.get_by_role("button", name="Acquire control", exact=True)
            ).to_be_hidden()
            await context.clock.run_for(250)
            assert len([c for c in calls if c["action"] == "robot.move"]) == moves
            await page.evaluate(
                "for (const p of [pad,other]) {p.buttons[4].pressed=false;p.axes.fill(0)}"
            )
            await context.clock.run_for(100)
            await page.get_by_role("button", name="Pop out all", exact=True).click()
            await expect(page.locator("#robots")).to_be_hidden()
            await expect(page.locator("#dock-all")).to_be_enabled()
            assert [c["params"]["camera"] for c in calls if c["action"] == "view.holoviz"] == [
                "first",
                "second",
            ]
            await page.get_by_role("button", name="Dock all", exact=True).click()
            await expect(page.locator("#robots")).to_be_visible()
            await expect(selector).to_have_value(selected)
            await expect(page.get_by_role("button", name="Dock all", exact=True)).to_be_disabled()
            closed = [
                (c["action"], c["params"]["camera"])
                for c in calls
                if c["action"] in {"view.browser", "view.close"}
            ]
            assert ("view.browser", "first") in closed
            assert ("view.close", "second") in closed
            assert ("view.close", "existing") in closed
            fail = True
            await page.get_by_role("button", name="Pop out robot controls", exact=True).click()
            await expect(page.locator("#notice")).to_contain_text("No desktop display")
            await expect(page.locator("#robots")).to_be_visible()
            assert len(context.pages) == 1 and not errors
            assert not any(c["action"] == "robot.release" for c in calls)
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selected,has_robot,expected",
    [
        ([], False, []),
        (["stopped"], False, []),
        (["first"], False, ["first"]),
        (["stale"], False, ["stale"]),
        ([], True, []),
    ],
)
async def test_popout_selection_and_robot_only(selected, has_robot, expected):
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": selected,
        "native_views": {},
        "session": {
            "id": "operator",
            "status": "approved",
            "robot": has_robot,
            "robots": [
                {
                    "id": "franka",
                    "name": "Franka",
                    "kind": "franka-sim",
                    "status": "online",
                    "controls": {"groups": {"joints": 7}, "step_deg": 0.4},
                    "state": {},
                }
            ]
            if has_robot
            else [],
            "cameras": [
                {
                    "id": name,
                    "name": name,
                    "kind": "fixture",
                    "codec": "h264",
                    "width": 640,
                    "height": 480,
                    "status": status,
                }
                for name, status in [
                    ("first", "live"),
                    ("unselected", "live"),
                    ("stale", "stale"),
                    ("stopped", "stopped"),
                ]
            ],
        },
    }
    calls = []

    async def route(request):
        path = urlsplit(request.request.url).path
        if path.startswith("/api/status"):
            await request.fulfill(json=state)
        elif path == "/api/action":
            call = request.request.post_data_json
            calls.append(call)
            if call["action"] == "view.holoviz":
                state["native_views"][call["params"]["camera"]] = {"status": "running"}
            await request.fulfill(json={"result": True})
        elif path == "/api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            context = await browser.new_context()
            await context.route("http://localhost:8777/**", route)
            await context.add_init_script(INPUT)
            page = await context.new_page()
            await page.goto("http://localhost:8777/")
            control = page.get_by_role("button", name="Pop out all", exact=True)
            if not expected and not has_robot:
                await expect(control).to_be_disabled()
            else:
                await control.click()
                assert len(context.pages) == 1
                await expect(control).not_to_have_attribute("aria-busy", "true")
                assert any(c["action"] == "controller.open" for c in calls) == has_robot
            assert [
                c["params"]["camera"] for c in calls if c["action"] == "view.holoviz"
            ] == expected
        finally:
            await browser.close()
