# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Operator and surgeon workflows keep devices scoped and live media independent of layout."""

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
PEER = """window.offers=0;window.closedPeers=0;window.RTCPeerConnection=class {
 constructor(){this.iceGatheringState='complete'}
 addTransceiver(){return {setCodecPreferences(){}}}
                createDataChannel(){return {readyState:'connecting',bufferedAmount:0,send(){}}}
 async createOffer(){window.offers++;return {type:'offer',sdp:'test'}}
 async setLocalDescription(d){this.localDescription=d}
 async setRemoteDescription(){} close(){window.closedPeers++}
 async getStats(){return new Map()}
};"""


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["patient", "surgeon"])
async def test_camera_action_columns_with_mixed_codecs_and_states(role):
    cameras = [
        {**camera("one", "Room camera"), "codec": "h264"},
        {**camera("two", "Endoscope", "stopped"), "codec": "raw-bgr8"},
        {**camera("three", "Wide room view with a long descriptive name"), "codec": "h265"},
        {**camera("four", "Wrist camera"), "codec": "h264"},
    ]
    for item in cameras:
        item["node"] = "host"
    state = {
        "role": role,
        "sdk": "5",
        "endpoint_port": 7447,
        "nodes": [{"id": "host", "name": "Room", "status": "online"}],
        "cameras": cameras,
        "robots": [],
        "surgeons": [],
        "selected": [item["id"] for item in cameras[2:]],
        "native_views": {item["id"]: {"status": "running"} for item in cameras[2:]},
        "session": {"status": "approved", "cameras": cameras, "robots": []},
    }

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            if role == "surgeon":
                await page.get_by_role("button", name="Add feeds", exact=True).first.click()
            root = "#equipment-rows" if role == "patient" else "#cameras"
            await expect(page.locator(f"{root} .camera-preview")).to_have_count(
                4 if role == "patient" else 3
            )
            await expect(page.locator(f"{root}")).not_to_contain_text("Holoviz only")
            if role == "surgeon":
                await expect(page.locator("#quick-feeds")).not_to_contain_text("Endoscope")
                await expect(page.locator("#cameras")).not_to_contain_text("Endoscope")
            await expect(page.locator(f"{root} .camera-preview:disabled")).to_have_count(
                3 if role == "patient" else 1
            )
            for width in (1600, 1280, 1024, 390):
                await page.set_viewport_size({"width": width, "height": 1000})
                for action in ("stream", "preview", "metrics", "display"):
                    boxes = await page.locator(f"{root} .camera-{action}").evaluate_all(
                        "nodes => nodes.map(node => {const b=node.getBoundingClientRect();"
                        "return {x:b.x,width:b.width,height:b.height}})"
                    )
                    if boxes:
                        assert all(abs(box["x"] - boxes[0]["x"]) < 1 for box in boxes)
                        assert all(abs(box["width"] - boxes[0]["width"]) < 1 for box in boxes)
                        assert all(box["height"] >= 34 for box in boxes)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert await page.locator(f"{root}").evaluate(
                    "node => node.scrollWidth <= node.clientWidth"
                )
            if role == "surgeon":
                cameras[1]["status"] = "live"
                await expect(page.locator("#quick-feeds")).to_contain_text("Endoscope")
                await expect(page.locator("#cameras")).to_contain_text("Endoscope")
                cameras[1]["status"] = "stopped"
                await expect(page.locator("#quick-feeds")).not_to_contain_text("Endoscope")
                await expect(page.locator("#cameras")).not_to_contain_text("Endoscope")
                await page.locator("#close-feeds").click()
            for width in (1600, 390):
                await page.set_viewport_size({"width": width, "height": 1000})
                native = page.locator("#native-views")
                offsets = await native.locator(".native-tile").evaluate_all(
                    "cards => cards.map(card => {const c=card.getBoundingClientRect();"
                    "return [...card.querySelectorAll('.actions button')].slice(0,2).map(b=>{"
                    "const r=b.getBoundingClientRect();return [r.x-c.x,r.bottom-c.bottom]})})"
                )
                assert offsets[0] == offsets[1]
        finally:
            await browser.close()


def camera(node, name, status="live"):
    return {
        "id": f"{node}:camera",
        "node": node,
        "name": name,
        "kind": "HSB IMX274" if node == "thor" else "USB",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "status": status,
        **({"receivers": ["fusa", "linux"], "receiver": "fusa"} if node == "thor" else {}),
    }


@pytest.mark.asyncio
async def test_patient_node_workflow_and_metrics():
    state = {
        "role": "patient",
        "sdk": "5.0",
        "endpoint_port": 7447,
        "nodes": [
            {"id": key, "name": name, "status": "online", "sdk": "5"}
            for key, name in (("host", "Workstation"), ("thor", "Thor"), ("spark", "DGX Spark"))
        ],
        "cameras": [
            camera("host", "Room camera"),
            camera("thor", "Endoscope", "stopped"),
            camera("spark", "Secondary room camera with a deliberately long descriptive label"),
        ],
        "robots": [
            {
                "id": "thor:robot",
                "node": "thor",
                "name": "MIRA",
                "kind": "mira-sim",
                "simulation": True,
                "controls": {"inputs": ["buttons", "gamepad"], "groups": {"left": 4, "right": 4}},
                "status": "online",
                "owner": "Dr. Lee",
            }
        ],
        "surgeons": [
            {"id": "one", "name": "Dr. Lee", "status": "approved", "requested_robot": True},
            {"id": "two", "name": "Dr. Patel", "status": "pending", "requested_robot": True},
        ],
        "native_views": {},
        "video": {},
        "timings": {},
        "clock": {"state": "unavailable", "detail": "Clock tracking unavailable"},
    }
    actions, metric_requests, log_requests, errors = [], [], [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            if "metrics=1" in path:
                metric_requests.append(True)
            await request.fulfill(json=state)
        elif path == "api/nodes/thor/log":
            log_requests.append(path)
            await request.fulfill(json={"text": "Node ready", "updated_seconds_ago": 0})
        elif path == "api/cameras/thor%3Acamera/log":
            log_requests.append(path)
            await request.fulfill(json={"text": "CoE capture stalled", "updated_seconds_ago": 0})
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            actions.append(body)
            if body["action"].startswith("camera."):
                item = next(c for c in state["cameras"] if c["id"] == body["params"]["id"])
                item["status"] = "stopped" if body["action"] == "camera.stop" else "live"
            elif body["action"] == "access.approve":
                state["surgeons"][1]["status"] = "approved"
            await request.fulfill(json={"result": True})
        elif path == "api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.add_init_script(PEER)
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await expect(page.get_by_role("heading", name="Room overview")).to_be_visible()
            assert not await page.locator("video").count()
            assert await page.locator("#patient-nav a").count() == 3
            await page.get_by_role("link", name="Nodes", exact=False).first.click()
            await expect(page.get_by_role("heading", name="Nodes", exact=True)).to_be_visible()
            await (
                page.locator("#nodes .device")
                .filter(has_text="Thor")
                .get_by_role("link", name="Thor equipment", exact=True)
                .click()
            )
            await expect(page.locator("#node-name")).to_have_text("Thor")
            await expect(page.locator("#equipment-rows")).not_to_contain_text("Room camera")
            await page.get_by_role("button", name="Node logs", exact=True).click()
            await expect(page.locator("#log-output")).to_have_text("Node ready")
            await page.evaluate(
                "window.getSelection().selectAllChildren(document.querySelector('#log-output'))"
            )
            await page.wait_for_timeout(1200)
            assert await page.evaluate("window.getSelection().toString()") == "Node ready"
            await expect(page.locator("#log-status")).to_have_text(
                "Updates paused while text is selected"
            )
            await page.context.grant_permissions(["clipboard-read", "clipboard-write"])
            await page.get_by_role("button", name="Copy logs", exact=True).click()
            assert await page.evaluate("navigator.clipboard.readText()") == "Node ready"
            await page.evaluate("window.getSelection().removeAllRanges()")
            await page.locator("#log-output").click()
            await expect(page.locator("#log-dialog")).to_be_visible()
            await page.mouse.click(10, 100)
            await expect(page.locator("#log-dialog")).to_be_hidden()
            count = len(log_requests)
            await page.wait_for_timeout(1200)
            assert len(log_requests) == count
            await page.get_by_role("button", name="Endoscope", exact=True).click()
            await page.get_by_role("button", name="Endoscope camera logs", exact=True).click()
            await expect(page.locator("#log-output")).to_have_text("CoE capture stalled")
            await page.locator("#close-log").click()
            await page.locator("#cameras .camera-settings").click()
            await expect(page.get_by_label("HSB receiver")).to_have_value("fusa")
            await page.get_by_label("HSB receiver").select_option("linux")
            await page.locator("#start-stream").click()
            assert actions[-1]["params"]["settings"]["receiver"] == "linux"
            await page.locator("#close-device-detail").click()
            await page.get_by_role("button", name="Stop all", exact=True).click()
            await page.get_by_role("button", name="Stream all", exact=True).click()
            await expect(page.get_by_role("button", name="Stop all", exact=True)).to_be_enabled()
            assert actions[-1] == {"action": "camera.start", "params": {"id": "thor:camera"}}
            await page.locator("#equipment-rows .camera-stream").click()
            await page.locator("#equipment-rows .camera-stream").click()
            assert actions[-1] == {"action": "camera.start", "params": {"id": "thor:camera"}}
            await expect(page.locator("#stream-dialog")).to_be_hidden()
            assert await page.evaluate("window.offers") == 0
            await page.get_by_role("button", name="Preview", exact=True).click()
            await page.wait_for_function("window.offers === 1")
            await page.get_by_role("link", name="Surgeons", exact=False).click()
            await (
                page.locator("#surgeons .device")
                .filter(has_text="Dr. Patel")
                .get_by_role("button", name="Approve robot")
                .click()
            )
            await expect(
                page.locator("#surgeons .device").filter(has_text="Dr. Patel")
            ).to_contain_text("approved")
            assert actions[-1]["params"]["robot"] is True
            assert state["cameras"][1]["status"] == "live"
            await page.goto("http://localhost:8777/#node/thor")
            await page.get_by_role("button", name="Endoscope", exact=True).click()
            await (
                page.locator("#device-detail-dialog")
                .get_by_role("button", name="Metrics", exact=True)
                .click()
            )
            await expect(page.locator("#device-detail-dialog")).to_be_hidden()
            await expect(page.locator("#metrics-title")).to_have_text("Endoscope")
            await expect(page.locator("#metrics-camera")).not_to_be_visible()
            await expect(page.locator('[data-card="fps"] h3')).to_have_text("Source frame rate")
            await page.get_by_role("button", name="Reset metrics").click()
            await page.locator("#close-metrics").click()
            await page.get_by_role("link", name="Overview", exact=True).click()
            count = len(metric_requests)
            await page.wait_for_timeout(1200)
            assert len(metric_requests) == count
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_surgeon_arranges_views_without_reconnecting_or_switching_controls():
    cameras = [camera("host", "Room camera"), camera("thor", "Endoscope")]
    state = {
        "role": "surgeon",
        "sdk": "5.0",
        "patient": "127.0.0.1:7447",
        "selected": [c["id"] for c in cameras],
        "native_views": {},
        "session": {
            "id": "one",
            "status": "approved",
            "robot": True,
            "cameras": cameras,
            "robots": [
                {
                    "id": "thor:mira",
                    "name": "MIRA",
                    "kind": "mira-sim",
                    "simulation": True,
                    "controls": {
                        "inputs": ["buttons", "gamepad"],
                        "groups": {"left": 4, "right": 4},
                    },
                    "status": "online",
                    "owner": None,
                },
                {
                    "id": "physical:mira",
                    "name": "MIRA",
                    "kind": "mira",
                    "status": "offline",
                    "controls": {"inputs": [], "groups": {}},
                },
                {
                    "id": "physical:franka",
                    "name": "Franka",
                    "kind": "franka",
                    "status": "unsupported",
                    "controls": {"inputs": [], "groups": {}},
                },
            ],
        },
    }
    actions, errors = [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            actions.append(body)
            if body["action"] == "view":
                state["selected"] = body["params"]["cameras"]
            await request.fulfill(json={"result": True})
        elif path == "api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1600, "height": 1000})
            await page.add_init_script(PEER)
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.context.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await expect(page.locator("video")).to_have_count(2)
            await expect(page.locator("#patient-nav")).to_be_hidden()
            await expect(page.locator("#robots-panel")).to_be_visible()
            await page.locator("#view-layout").select_option("two")
            await page.get_by_role("button", name="Edit layout", exact=True).click()
            await page.get_by_role("button", name="Move Endoscope earlier", exact=True).click()
            await expect(page.locator('[data-camera="thor:camera"]')).to_have_css("order", "0")
            await page.get_by_role("button", name="Done arranging").click()
            assert await page.evaluate("window.offers") == 2
            assert await page.evaluate("window.closedPeers") == 0
            await (
                page.locator('[data-camera="thor:camera"]')
                .get_by_role("button", name="Metrics", exact=True)
                .click()
            )
            await expect(page.locator("#metrics-title")).to_have_text("Endoscope")
            assert len(page.context.pages) == 1
            assert await page.evaluate("window.offers") == 2
            await page.locator("#close-metrics").click()
            await page.get_by_role("button", name="Add feeds", exact=True).first.click()
            await page.locator("#camera-search").fill("Endoscope")
            await expect(page.locator("#cameras .device:visible")).to_have_count(1)
            heading = page.locator("#feed-title")
            await heading.click()
            await expect(page.locator("#feed-dialog")).to_be_visible()
            # A drag that starts inside must not dismiss the dialog.
            await heading.hover()
            await page.mouse.down()
            await page.mouse.move(10, 100)
            await page.mouse.up()
            await expect(page.locator("#feed-dialog")).to_be_visible()
            await page.mouse.click(10, 100)
            await expect(page.locator("#feed-dialog")).to_be_hidden()
            assert await page.evaluate("window.offers") == 2
            assert not actions
            await (
                page.locator("#quick-feeds")
                .get_by_role("button", name="Hide Endoscope", exact=True)
                .click()
            )
            await expect(page.locator("video")).to_have_count(1)
            await (
                page.locator("#quick-feeds")
                .get_by_role("button", name="Show Endoscope", exact=True)
                .click()
            )
            await expect(page.locator("video")).to_have_count(2)
            await expect(page.locator("#feed-dialog")).to_be_hidden()
            await page.reload()
            await expect(page.locator("#view-layout")).to_have_value("two")
            await expect(page.locator('[data-camera="thor:camera"]')).to_have_css("order", "0")
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            state["session"]["robot"] = False
            await expect(page.locator("#robots-panel")).to_contain_text("View-only access")
            await expect(page.locator("#robots .joint-groups")).to_have_count(0)
            assert await page.locator("#operating-workspace").evaluate(
                "node => node.classList.contains('has-robot')"
            )
            await expect(page.locator("#robot-selector option")).to_have_text(["MIRA · Simulation"])
            state["session"]["robots"][1]["status"] = "online"
            state["session"]["robots"][2]["status"] = "online"
            await expect(page.locator("#robot-selector option")).to_have_text(
                ["Franka · Physical", "MIRA · Physical", "MIRA · Simulation"]
            )
            await page.locator("#robot-selector").select_option("physical:mira")
            await expect(page.locator("#robots")).to_contain_text("View-only access")
            await page.locator("#robot-selector").select_option("physical:franka")
            await expect(page.locator("#robots")).to_contain_text("View-only access")
            await expect(page.locator("#robots .joint-groups")).to_have_count(0)
            await page.reload()
            await expect(page.locator("#robot-selector")).to_have_value("physical:franka")
            # A reconnect may deliver inventory in stages. Do not overwrite the
            # remembered choice while its node is temporarily absent.
            selected = state["session"]["robots"].pop()
            await expect(page.locator("#robot-selector option:not(:disabled)")).to_have_count(2)
            await expect(page.locator("#robot-selector")).to_have_value("")
            state["session"]["robots"].append(selected)
            await expect(page.locator("#robot-selector")).to_have_value("physical:franka")
            address = state.get("patient")
            state["patient"] = "another-room:7447"
            await expect(page.locator("#subtitle")).to_have_text("another-room:7447")
            await expect(page.locator("#robot-selector")).to_have_value("physical:franka")
            await page.locator("#robot-selector").select_option("physical:mira")
            state["patient"] = address
            await expect(page.locator("#robot-selector")).to_have_value("physical:franka")
            assert not any(a["action"].startswith("robot.") for a in actions)
            await page.get_by_role("button", name="Hide all", exact=True).click()
            await expect(page.locator("video")).to_have_count(0)
            assert all(c["status"] == "live" for c in cameras)
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("robot_count", [1, 3])
async def test_patient_inline_previews_preserve_media_and_alignment(robot_count):
    def camera_item(index):
        return {**camera("host", f"Procedure camera {index}"), "id": f"host:camera-{index}"}

    state = {
        "role": "patient",
        "sdk": "5.0",
        "endpoint_port": 7447,
        "nodes": [{"id": "host", "name": "Operating room", "status": "online"}],
        "cameras": [camera_item(i) for i in range(1, 3)],
        "robots": [
            {
                "id": f"host:robot-{i}",
                "name": "MIRA" if i == 0 else f"Franka arm {i}",
                "kind": "mira-sim" if i == 0 else "franka-sim",
                "status": "online",
                "owner": None,
            }
            for i in range(robot_count)
        ],
        "surgeons": [],
        "native_views": {},
    }
    errors = []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif path == "api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1600, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.add_init_script(PEER)
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await expect(page.locator("#node-name")).to_have_text("Operating room")
            await expect(page.get_by_role("button", name="Add node", exact=True)).to_have_count(0)
            assert await page.locator("#node-search").count() == 0
            await expect(page.get_by_role("link", name="← All nodes")).not_to_be_visible()
            await page.get_by_role("link", name="Overview", exact=True).click()
            await expect(page.locator("#device-workspace")).not_to_be_visible()
            await page.get_by_role("link", name="Nodes", exact=False).first.click()
            rows = page.locator("#equipment-rows tr")
            await expect(rows).to_have_count(2 + robot_count)
            await expect(page.locator("#equipment-panel")).to_be_visible()
            await expect(page.locator("#views-panel")).to_be_hidden()
            for count in (1, 2):
                await (
                    page.locator("#equipment-rows")
                    .get_by_role("button", name="Preview", exact=True)
                    .first.click()
                )
                await expect(page.locator("video")).to_have_count(count)
                await expect(page.locator("#equipment-panel")).to_be_visible()
                await expect(page.locator("#views-panel")).to_be_visible()
                video = page.locator("video").first
                original_height = (await video.bounding_box())["height"]
                await (
                    page.locator(".video-tile")
                    .first.get_by_role("button", name="Fullscreen", exact=True)
                    .click()
                )
                await page.wait_for_function("document.fullscreenElement !== null")
                await page.wait_for_function(
                    """originalHeight => {
                        const tile = document.fullscreenElement;
                        const bounds = tile.getBoundingClientRect();
                        return Math.abs(bounds.width - innerWidth) < 1
                            && Math.abs(bounds.height - innerHeight) < 1
                            && tile.querySelector('video').getBoundingClientRect().height
                                > originalHeight;
                    }""",
                    arg=original_height,
                )
                await page.get_by_role("button", name="Exit fullscreen", exact=True).first.click()
                await page.wait_for_function("document.fullscreenElement === null")
            assert await page.evaluate("window.offers") == 2
            assert await page.evaluate("window.closedPeers") == 0
            state["cameras"].extend(camera_item(i) for i in range(3, 7))
            await expect(rows).to_have_count(6 + robot_count)
            for width in (1600, 1280, 1024, 390):
                await page.set_viewport_size({"width": width, "height": 900})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await expect(page.locator("#views-panel")).to_be_visible()
                if width > 700:
                    for col in ("Device", "Type", "Status", "Details", "Actions"):
                        positions = await page.locator(
                            f'#equipment-rows td[data-label="{col}"]'
                        ).evaluate_all("cells => cells.map(c => c.getBoundingClientRect().x)")
                        assert max(positions) - min(positions) < 1
            for _ in range(2):
                await (
                    page.locator("#equipment-rows")
                    .get_by_role("button", name="Hide preview", exact=True)
                    .first.click()
                )
            await expect(page.locator("video")).to_have_count(0)
            assert not errors
        finally:
            await browser.close()
