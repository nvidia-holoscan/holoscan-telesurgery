# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Detached controls transfer input ownership, and stop on focus loss or closure."""

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
navigator.getGamepads = () => [window.pad];
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
@pytest.mark.parametrize("kind", ["franka", "mira"])
async def test_detached_keyboard_gamepad_and_docking(tmp_path, kind):
    robot = {
        "id": f"node:{kind}",
        "name": kind.title(),
        "kind": kind,
        "status": "online",
        "controls": (
            controls(MiraSimulation({"uri": "unused"}), {"motion_enabled": True})
            if kind == "mira"
            else {
                "inputs": ["keyboard", "gamepad"],
                "groups": {"joints": 7},
                "default_step_deg": 1,
                "max_step_deg": 5,
                "home_deg": {"joints": FRANKA_HOME},
                "speed_deg_s": FRANKA_SPEED,
            }
        ),
        "state": {"sequence": 1, "control_active": False},
    }
    offline = {**robot, "id": "offline", "name": "Offline", "status": "disconnected"}
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": ["existing", "first", "second", "stopped"],
        "native_views": {"existing": {"status": "running"}},
        "session": {
            "id": "operator",
            "status": "approved",
            "robot": True,
            "robots": [robot, offline],
            "cameras": [
                {
                    "id": key,
                    "name": key,
                    "kind": "fixture",
                    "codec": codec,
                    "width": 1920,
                    "height": 1080,
                    "status": status,
                }
                for key, codec, status in [
                    ("existing", "bgr8", "live"),
                    ("first", "h264", "live"),
                    ("second", "h265", "live"),
                    ("unselected", "h264", "live"),
                    ("stopped", "h264", "stopped"),
                ]
            ],
        },
    }
    calls, errors = [], []

    async def route(request):
        path = urlsplit(request.request.url).path
        if path.startswith("/api/status"):
            await request.fulfill(json=state)
        elif path == "/api/action":
            call = request.request.post_data_json
            calls.append(call)
            if call["action"] == "view.holoviz":
                camera = call["params"]["camera"]
                if kind == "mira" and camera == "first":
                    await request.fulfill(status=409, json={"error": "Viewer unavailable"})
                    return
                state["native_views"][camera] = {"status": "running"}
                if camera not in state["selected"]:
                    state["selected"].append(camera)
            elif call["action"] in {"view.browser", "view.close"}:
                camera = call["params"]["camera"]
                state["native_views"].pop(camera, None)
                if call["action"] == "view.close" and camera in state["selected"]:
                    state["selected"].remove(camera)
            if call["action"] == "robot.move":
                robot.update(owner="Operator", owner_id="operator")
                robot["state"]["control_active"] = True
            elif call["action"] == "robot.release":
                robot.update(owner=None, owner_id=None)
                robot["state"]["control_active"] = False
            robot["state"]["sequence"] += 1
            await request.fulfill(json={"result": robot["state"]})
        elif path == "/api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    def moves():
        return [call for call in calls if call["action"] == "robot.move"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--window-size=1440,1000", "--screen-info={0,0 1920x1080}"]
        )
        try:
            context = await browser.new_context(no_viewport=True)
            await context.clock.install(time=1000)
            await context.route("http://localhost:8777/**", route)
            await context.add_init_script(INPUT)
            context.on("page", lambda page: page.on("pageerror", lambda e: errors.append(str(e))))
            page = await context.new_page()
            await page.goto("http://localhost:8777/")
            await expect(page.locator("#robot-selector option")).to_have_count(1)
            setting = "arm speed"
            step_label = f"{robot['name']} {setting}"

            async def change_speed(page, value):
                control = page.get_by_label(step_label, exact=True)
                await control.focus()
                await control.evaluate(
                    "(s,v) => {s.value=v;s.dispatchEvent(new Event('input'))}", value
                )
                await control.press("Enter")

            first_speed, second_speed = "30", "40"
            await change_speed(page, first_speed)
            async with page.expect_popup() as event:
                await page.get_by_role("button", name="Pop out all", exact=True).click()
            popup = await event.value
            await expect(popup.get_by_label(step_label, exact=True)).to_have_value(first_speed)
            await expect(page.get_by_role("button", name="Pop out all", exact=True)).to_be_enabled()
            assert [c["params"]["camera"] for c in calls if c["action"] == "view.holoviz"] == [
                "first",
                "second",
            ]
            if kind == "mira":
                await expect(page.locator("#notice")).to_contain_text("first: Viewer unavailable")
            await popup.wait_for_function("document.documentElement.scrollHeight <= innerHeight")
            keyboard_height = await popup.evaluate("outerHeight")
            await expect(page.locator("#robots")).to_be_hidden()
            await expect(popup.locator("#camera-workspace")).to_be_hidden()
            await expect(popup.get_by_role("button", name="Home", exact=True)).to_be_enabled()
            # Both windows share this clock. Advance every input poll instead
            # of making a loaded CI worker satisfy the 200 ms stall watchdog.
            await context.clock.pause_at(10000)
            await context.clock.run_for(50)
            await popup.locator(".keyboard-controls").focus()
            await popup.keyboard.down("q")
            await context.clock.run_for(850)
            assert len(moves()) >= 3
            assert moves()[0]["params"]["mode"] == "step"
            assert moves()[-1]["params"]["mode"] == "jog"
            # Background dashboard polling and input cannot cancel or duplicate
            # the child's motion, even when status says this surgeon owns it.
            count = len(moves())
            await page.evaluate(
                "window.dispatchEvent(new Event('blur')); "
                "window.dispatchEvent(new KeyboardEvent('keydown', {key:'q'}))"
            )
            await context.clock.run_for(1100)
            assert len(moves()) > count
            assert not [c for c in calls if c["action"] == "robot.release"]
            # A genuinely missed polling deadline must still stop held input.
            await context.clock.fast_forward(250)
            await context.clock.run_for(150)
            assert calls[-1]["action"] == "robot.release"
            count = len(moves())
            await context.clock.run_for(200)
            assert len(moves()) == count
            await popup.keyboard.up("q")
            await popup.keyboard.down("q")
            await context.clock.run_for(650)
            assert len(moves()) > count
            assert moves()[-1]["params"]["mode"] == "jog"
            await popup.evaluate("inputFocus=false; window.dispatchEvent(new Event('blur'))")
            await context.clock.run_for(150)
            assert calls[-1]["action"] == "robot.release"
            count = len(moves())
            await context.clock.run_for(200)
            assert len(moves()) == count
            await popup.keyboard.up("q")
            await popup.evaluate("inputFocus=true")
            await popup.get_by_label(f"{robot['name']} input", exact=True).select_option("0")
            await context.clock.run_for(50)
            await expect(popup.locator(".gamepad-controls")).to_have_attribute(
                "data-state", "ready"
            )
            await popup.evaluate("pad.buttons[4].pressed=true; pad.axes[0]=1")
            await context.clock.run_for(250)
            assert len(moves()) > count
            await popup.evaluate("inputFocus=false; window.dispatchEvent(new Event('blur'))")
            await context.clock.run_for(150)
            assert calls[-1]["action"] == "robot.release"
            count = len(moves())
            await popup.evaluate("inputFocus=true")
            await context.clock.run_for(200)
            assert len(moves()) == count  # Held deadman cannot resume after refocus.
            await popup.evaluate("pad.buttons[4].pressed=false; pad.axes.fill(0)")
            await context.clock.run_for(50)
            await context.clock.resume()
            await expect(popup.locator(".gamepad-controls")).to_have_attribute(
                "data-state", "ready"
            )
            if kind == "franka":
                await popup.wait_for_function("height => outerHeight < height", arg=keyboard_height)
            await popup.wait_for_function("document.documentElement.scrollHeight <= innerHeight")
            await popup.screenshot(path=str(tmp_path / f"{kind}-controller-gamepad.png"))
            await popup.get_by_label(f"{robot['name']} input", exact=True).select_option("keyboard")
            await change_speed(popup, second_speed)
            await popup.locator(".keyboard-controls").focus()
            await popup.wait_for_function("document.documentElement.scrollHeight <= innerHeight")
            await popup.screenshot(path=str(tmp_path / f"{kind}-controller-keyboard.png"))
            await expect(page.get_by_role("button", name="Dock all", exact=True)).to_be_enabled()
            await page.get_by_role("button", name="Dock all", exact=True).click()
            await expect(page.get_by_label(step_label, exact=True)).to_have_value(second_speed)
            await expect(page.get_by_role("button", name="Dock all", exact=True)).to_be_disabled()
            closed = [
                (c["action"], c["params"]["camera"])
                for c in calls
                if c["action"] in {"view.browser", "view.close"}
            ]
            assert ("view.close", "existing") in closed
            assert ("view.close", "second") in closed
            assert (("view.browser", "first") in closed) == (kind == "franka")
            assert popup.is_closed()
            # Closing the native title bar during a held key also stops motion.
            async with page.expect_popup() as event:
                await page.get_by_role("button", name="Pop out robot controls", exact=True).click()
            popup = await event.value
            await expect(popup.get_by_label(step_label, exact=True)).to_have_value(second_speed)
            await context.clock.pause_at(20000)
            await context.clock.run_for(50)
            await popup.locator(".keyboard-controls").focus()
            await popup.keyboard.down("q")
            await context.clock.run_for(650)
            await popup.close()
            await expect(page.get_by_label(step_label, exact=True)).to_be_visible()
            await context.clock.run_for(200)
            assert calls[-1]["action"] == "robot.release"
            count = len(moves())
            await context.clock.run_for(250)
            assert len(moves()) == count
            await context.clock.resume()
            # Disconnection never silently selects a different robot.
            robot["status"] = "disconnected"
            offline["status"] = "online"
            await expect(page.locator("#robot-selector")).to_have_value("")
            await expect(page.locator("#robots")).to_contain_text("Select a robot")
            await page.locator("#robot-selector").select_option("offline")
            await expect(page.get_by_label(f"Offline {setting}", exact=True)).to_be_visible()
            # A blocked popup leaves the original controls usable.
            await page.evaluate("window.open = () => null")
            await page.get_by_role("button", name="Pop out robot controls", exact=True).click()
            await expect(page.locator("#notice")).to_contain_text("Allow pop-ups")
            await expect(page.get_by_label(f"Offline {setting}", exact=True)).to_be_visible()
            assert not errors
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
                if has_robot:
                    async with page.expect_popup() as event:
                        await control.click()
                    popup = await event.value
                    await expect(popup.get_by_label("Franka input", exact=True)).to_be_visible()
                else:
                    await control.click()
                await expect(control).not_to_have_attribute("aria-busy", "true")
            assert [
                c["params"]["camera"] for c in calls if c["action"] == "view.holoviz"
            ] == expected
        finally:
            await browser.close()
