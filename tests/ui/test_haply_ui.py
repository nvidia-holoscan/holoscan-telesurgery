# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Headless checks for browser Haply selection and cancellation of delayed input."""

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
@pytest.mark.parametrize("kind", ["mira", "franka", "future-cartesian-robot"])
async def test_haply_physical_and_new_adapters_share_ui_and_require_acquisition(kind):
    from telesurgery_robots.franka.adapter import Franka
    from telesurgery_robots.mira.adapter import MiraAdapter

    adapter = MiraAdapter({"uri": "unused"}) if kind == "mira" else Franka.__new__(Franka)
    robot = {
        "id": "test-arm",
        "name": "Test arm",
        "kind": kind,
        "simulation": False,
        "status": "online",
        "controls": controls(adapter, {"motion_enabled": True}),
        "state": {
            "sequence": 1,
            **(
                {"cartesian_mm_deg": {"left": [12, -23, 34, 25], "right": [-12, -23, 34, 25]}}
                if kind == "mira"
                else {"tool_pose": {"position_m": [0.012, -0.023, 0.034]}}
            ),
        },
    }
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "native_views": {},
        "native_controller": {"status": "closed"},
        "haply_available": True,
        "session": {
            "id": "operator",
            "name": "Operator",
            "status": "approved",
            "robot": True,
            "robots": [robot],
            "cameras": [],
        },
    }
    actions, errors = [], []
    result = {
        "request": None,
        "paused": True,
        "arm": "left" if kind == "mira" else "hand",
        "error": "",
        "calibration": {"collecting": False, "ready": False, "span_mm": []},
    }

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            body = request.request.post_data_json
            actions.append(body)
            if body["action"] == "haply.read" and (
                calibration := body["params"].get("calibration")
            ):
                result["calibration"] = {
                    "collecting": calibration == "start",
                    "ready": calibration == "save",
                    "span_mm": [200, 180, 160],
                }
            await request.fulfill(
                json={"result": result if body["action"] == "haply.read" else robot["state"]}
            )
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            async with page.expect_request(
                lambda request: (
                    request.url.endswith("/api/action")
                    and request.post_data_json.get("action") == "haply.read"
                )
            ):
                await page.get_by_label("Test arm input", exact=True).select_option("haply")
            await expect(page.locator(".haply-coordinate")).to_have_text(["12.0", "-23.0", "34.0"])
            await expect(page.locator(".axis-triad")).to_be_visible()
            await expect(page.locator(".haply-calibration")).to_be_visible()
            await page.get_by_role("button", name="Calibrate Haply movement range").click()
            await expect(page.locator(".haply-range")).to_contain_text("Calibration active")
            await page.get_by_role("button", name="Calibrate Haply movement range").click()
            await expect(page.locator(".haply-range")).to_contain_text("Movement range saved")
            await expect(page.locator(".haply-controls [role=status]")).to_have_text(
                "Paused · Left arm" if kind == "mira" else "Paused"
            )
            assert actions and all(a["action"] == "haply.read" for a in actions)
            assert all(a["params"]["enabled"] is False for a in actions)
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            motion = (
                ["cartesian", {"left": [0.1, 0, 0, 0, 0], "right": [0] * 5}]
                if kind == "mira"
                else ["jog", {"translation": [0.1, 0, 0], "rotation": [0, 0, 0]}]
            )
            async with page.expect_request(
                lambda request: (
                    request.url.endswith("/api/action")
                    and request.post_data_json.get("action") == "robot.move"
                )
            ) as sent:
                result.update(request=motion, paused=False)
            command = (await sent.value).post_data_json["params"]
            assert command["mode"] == motion[0] and command["command"] == motion[1]
            assert next(a for a in actions if a["action"] == "haply.read")["params"]["speeds"][
                "arm"
            ] == robot["controls"].get("default_arm_speed_percent", 20)
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["mira", "franka", "versius"])
async def test_haply_browser_selection_focus_stop_and_delayed_reply(kind):
    name = {"mira": "MIRA", "franka": "Franka", "versius": "Versius left"}[kind]
    adapter = {"mira": MiraSimulation, "franka": FrankaSimulation, "versius": VersiusSimulation}[
        kind
    ]
    robot = {
        "id": kind,
        "name": name,
        "kind": kind + "-sim",
        "simulation": True,
        "status": "online",
        "controls": controls(adapter({"uri": "unused"}), {"motion_enabled": True}),
        "state": {"sequence": 1, "grippers": {"left": 0, "right": 1}},
    }
    if kind == "franka":
        robot["controls"]["grippers"] = []
    state = {
        "role": "surgeon",
        "sdk": "5",
        "selected": [],
        "native_views": {},
        "native_controller": {"status": "closed"},
        "session": {
            "id": "operator",
            "name": "Operator",
            "status": "approved",
            "robot": True,
            "robots": [robot],
            "cameras": [],
        },
    }
    calls, errors = [], []
    result = {"request": None, "paused": True, "arm": "left", "error": "Calibrate the Inverse3."}
    result["calibration"] = {"collecting": False, "ready": False, "span_mm": []}
    gate = None

    async def route(request):
        path = urlsplit(request.request.url).path
        if path == "/api/status":
            await request.fulfill(json=state)
        elif path == "/api/action":
            body = request.request.post_data_json
            calls.append(body)
            if body["action"] == "haply.read":
                calibration = body["params"].get("calibration")
                if calibration:
                    result["calibration"] = {
                        "collecting": calibration == "start",
                        "ready": calibration == "save",
                        "span_mm": [200, 180, 160],
                    }
                reply = dict(result)
                if gate is not None:
                    await gate.wait()
                await request.fulfill(json={"result": reply})
            else:
                robot["state"]["sequence"] += 1
                await request.fulfill(json={"result": robot["state"]})
        else:
            await request.fulfill(
                path=STATIC / (path.removeprefix("/static/") if path != "/" else "index.html")
            )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(bypass_csp=True)
            await context.add_init_script("""
                window.focused = true;
                document.hasFocus = () => window.focused;
                window.pads = [];
                navigator.getGamepads = () => window.pads;
            """)
            await context.route("http://localhost:8777/**", route)
            page = await context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto("http://localhost:8777/")
            selector = page.get_by_label(f"{name} input", exact=True)
            await expect(selector.locator('option[value="haply"]')).to_have_count(0)
            assert not any(c["action"] == "haply.read" for c in calls)
            state["haply_available"] = True
            await expect(selector.locator('option[value="haply"]')).to_have_count(1)
            await selector.select_option("haply")
            await expect(page.locator(".haply-controls")).to_be_visible()
            await expect(page.locator(".gamepad-controls:not(.haply-controls)")).to_be_hidden()
            await expect(page.get_by_label(f"{name} arm speed", exact=True)).to_be_visible()
            coordinates = page.locator(".haply-coordinate")
            await expect(coordinates).to_have_text(["—", "—", "—"])
            if kind == "mira":
                robot["state"]["cartesian_mm_deg"] = {
                    "left": [50, -550, 530, 25],
                    "right": [-50, -540, 520, 25],
                }
                expected = ["50.0", "-550.0", "530.0"]
            else:
                robot["state"]["tool_pose"] = {"position_m": [0.0123, -0.0456, 0.0789]}
                expected = ["12.3", "-45.6", "78.9"]
            await expect(coordinates).to_have_text(expected)
            # Stale feedback is not presented as a live position.
            robot["stale"] = True
            await expect(coordinates).to_have_text(["—", "—", "—"])
            robot["stale"] = False
            await expect(coordinates).to_have_text(expected)
            if kind == "mira":
                result["arm"] = "right"
                await expect(coordinates).to_have_text(["-50.0", "-540.0", "520.0"])
                result["arm"] = "left"
                await expect(coordinates).to_have_text(expected)
            result["tracking_ready"] = False
            result["tracking_error"] = (
                "VerseGrip not detected. Power on the pen and connect its USB dongle."
            )
            result["error"] = result["tracking_error"]
            await expect(
                page.get_by_role("button", name="Calibrate Haply movement range")
            ).to_be_disabled()
            await expect(page.locator(".haply-calibration-error")).to_contain_text(
                "VerseGrip not detected"
            )
            await expect(page.locator(".haply-controls .input-discovery")).to_be_hidden()
            await expect(page.locator(".haply-range")).to_be_hidden()
            result["tracking_ready"] = True
            result["tracking_error"] = ""
            result["error"] = "Calibrate the Inverse3."
            await expect(
                page.get_by_role("button", name="Calibrate Haply movement range")
            ).to_be_enabled()
            await expect(page.locator(".haply-calibration-error")).to_be_hidden()
            await page.get_by_role("button", name="Calibrate Haply movement range").click()
            await expect(page.locator(".haply-range")).to_contain_text("Calibration active")
            await expect(page.locator(".haply-range")).to_contain_text("200 / 180 / 160 mm")
            await expect(page.get_by_role("button", name="Cancel", exact=True)).to_be_visible()
            await page.get_by_role("button", name="Calibrate Haply movement range").click()
            await expect(page.locator(".haply-range")).to_contain_text("Movement range saved")
            await expect(page.get_by_role("button", name="Cancel", exact=True)).to_be_hidden()
            assert not any(c["action"].startswith("robot.") for c in calls)
            if kind == "mira":
                await expect(page.get_by_label(f"{name} roll speed", exact=True)).to_be_visible()
            assert not any(c["action"] == "robot.move" for c in calls)
            await expect(page.locator(".haply-controls")).to_contain_text(
                "Tap single-dot button · Start / stop"
            )
            if kind == "mira":
                await expect(page.locator(".haply-controls")).to_contain_text(
                    "Tap two-dot button · Switch"
                )
                await expect(page.locator(".haply-controls")).not_to_contain_text("A + C")
                await expect(page.locator(".haply-controls")).to_contain_text(
                    "Hold single-dot button · Close gripper"
                )
                await expect(
                    page.locator(".haply-controls .gripper-controls button:visible")
                ).to_have_count(0)
                await expect(
                    page.locator(".haply-controls .gripper-feedback meter:visible")
                ).to_have_count(2)
            await expect(page.locator(".haply-controls .input-discovery")).to_have_text(
                "Calibrate the Inverse3."
            )
            await expect(page.locator(".haply-controls .motion-section").nth(1)).to_contain_text(
                "Twist pen · Roll tool"
            )
            await expect(page.locator(".haply-controls .motion-section").nth(0)).to_contain_text(
                "Tilt pen up / down · Angle tool" if kind == "mira" else "Tilt pen · Angle tool"
            )
            # Gamepad discovery refresh must preserve Haply selection.
            await page.evaluate("""window.pads = [{
                id:'Xbox',index:0,connected:true,mapping:'standard',
                axes:[0,0,0,0],buttons:Array.from({length:17},()=>({pressed:false,value:0}))}]""")
            await expect(selector.locator("option")).to_have_count(3)
            await expect(selector).to_have_value("haply")
            # Input selection is a local preference; every device remains idle
            # until the surgeon explicitly acquires control.
            await selector.select_option("0")
            await expect(page.locator(".gamepad-controls:not(.haply-controls)")).to_be_visible()
            await page.evaluate("pads[0].buttons[4].pressed=true;pads[0].axes[0]=1")
            await page.wait_for_timeout(150)
            await selector.select_option("keyboard")
            await expect(page.locator(".keyboard-controls")).to_be_visible()
            await page.keyboard.press("q")
            await selector.select_option("haply")
            await page.wait_for_timeout(150)
            assert not any(c["action"].startswith("robot.") for c in calls)
            reads = [c for c in calls if c["action"] == "haply.read"]
            assert reads and all(not c["params"]["enabled"] for c in reads)
            await page.get_by_role("button", name="Acquire control", exact=True).click()
            await expect(page.locator(".haply-controls .input-discovery")).to_have_text(
                "Calibrate the Inverse3."
            )
            motion = (
                ["cartesian", {"left": [0.1, 0, 0, 0, 0], "right": [0] * 5}]
                if kind == "mira"
                else ["jog", {"translation": [0.1, 0, 0], "rotation": [0, 0, 0]}]
            )
            result.update(request=motion, paused=False, error="")
            await expect(page.locator(".haply-controls [role=status]")).to_have_text(
                "Active · Left arm" if kind == "mira" else "Active"
            )
            for _ in range(40):
                if any(c["action"] == "robot.move" for c in calls):
                    break
                await asyncio.sleep(0.025)
            assert any(c["action"] == "robot.move" for c in calls)
            # Incoming movement acknowledgements refresh measured XYZ as well.
            if kind == "mira":
                robot["state"]["cartesian_mm_deg"]["left"][0] = 55.5
            else:
                robot["state"]["tool_pose"]["position_m"][0] = 0.0555
            await expect(coordinates).to_have_text(["55.5", *expected[1:]])
            result.update(
                request=None, paused=True, error="Haply tracking jumped; tap Start to resume."
            )
            await expect(page.locator(".haply-controls .input-discovery")).to_contain_text(
                "Haply tracking jumped"
            )
            result["error"] = ""
            await asyncio.sleep(0.15)
            await expect(page.locator(".haply-controls .input-discovery")).to_contain_text(
                "Haply tracking jumped"
            )
            result.update(request=motion, paused=False)
            await expect(page.locator(".haply-controls .input-discovery")).to_be_hidden()
            assert next(c for c in calls if c["action"] == "haply.read")["params"]["speeds"] == {
                "arm": 20,
                "roll": 50,
                "grip": 40,
            }
            # Escape during an outstanding read must discard that response.
            gate = asyncio.Event()
            before = sum(c["action"] == "haply.read" for c in calls)
            while sum(c["action"] == "haply.read" for c in calls) == before:
                await asyncio.sleep(0.025)
            result.update(request=None, paused=True)
            await page.keyboard.press("Escape")
            sent = sum(c["action"] == "robot.move" for c in calls)
            gate.set()
            gate = None
            await asyncio.sleep(0.15)
            assert sum(c["action"] == "robot.move" for c in calls) == sent
            assert any(c["action"] == "robot.hold" for c in calls)
            # A hidden/unfocused browser never forwards device motion.
            await page.evaluate("window.focused = false; window.dispatchEvent(new Event('blur'))")
            result.update(request=motion, paused=False)
            await asyncio.sleep(0.2)
            assert sum(c["action"] == "robot.move" for c in calls) == sent
            assert any(c["action"] == "haply.read" and not c["params"]["enabled"] for c in calls)
            await page.evaluate("window.focused = true")
            result.update(request=None, paused=True)
            reset = page.get_by_role("button", name="Reset scene", exact=True)
            await expect(reset).to_be_visible()
            assert await reset.locator("svg").count() == 1
            hint = {
                "mira": "Reset both arms and the needle.",
                "franka": "Reset the arm and probe to their starting positions.",
                "versius": "Reset all four arms and the needle.",
            }[kind]
            await expect(reset).to_have_attribute("title", hint)
            if kind == "versius":
                robot["reset_scene_blocked"] = "Release control of all other arms before resetting."
                await expect(reset).to_be_disabled()
                await expect(reset).to_have_attribute(
                    "title", hint + " " + robot["reset_scene_blocked"]
                )
                assert not any(c.get("params", {}).get("mode") == "reset" for c in calls)
                robot["reset_scene_blocked"] = ""
                await expect(reset).to_be_enabled()
            async with page.expect_request(
                lambda r: (
                    r.url.endswith("/api/action")
                    and r.post_data_json.get("action") == "robot.move"
                    and r.post_data_json["params"].get("mode") == "reset"
                )
            ):
                await reset.click()
            stop_button = page.get_by_role("button", name="Stop", exact=True)
            assert await stop_button.locator("svg").count() == 1
            assert await stop_button.locator("kbd").count() == 0
            state["haply_available"] = False
            await expect(selector.locator('option[value="haply"]')).to_have_count(0)
            await expect(selector).to_have_value("keyboard")
            await expect(page.locator(".haply-controls")).to_be_hidden()
            assert errors == []
        finally:
            if gate:
                gate.set()
            await browser.close()
