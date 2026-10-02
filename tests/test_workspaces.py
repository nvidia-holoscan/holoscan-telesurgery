# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Operator and surgeon workflows keep devices scoped and live media independent of layout."""

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[1] / "packages/app/src/telesurgery/server/static"
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
async def test_camera_action_columns_with_mixed_codecs_and_states(role, tmp_path):
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
            await expect(page.locator("#cameras .device")).to_have_count(4)
            await expect(page.locator("#cameras")).not_to_contain_text("Holoviz only")
            await expect(page.locator("#cameras .camera-preview")).to_have_count(4)
            await expect(page.locator("#cameras .camera-preview:disabled")).to_have_count(
                3 if role == "patient" else 2
            )
            for width in (1600, 1280, 1024, 390):
                await page.set_viewport_size({"width": width, "height": 1000})
                for action in ("stream", "preview", "metrics", "display"):
                    boxes = await page.locator(f"#cameras .camera-{action}").evaluate_all(
                        "nodes => nodes.map(node => {const b=node.getBoundingClientRect();"
                        "return {x:b.x,width:b.width,height:b.height}})"
                    )
                    if boxes:
                        assert all(abs(box["x"] - boxes[0]["x"]) < 1 for box in boxes)
                        assert all(abs(box["width"] - boxes[0]["width"]) < 1 for box in boxes)
                        assert all(box["height"] >= 34 for box in boxes)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert await page.locator("#cameras").evaluate(
                    "node => node.scrollWidth <= node.clientWidth"
                )
                await page.screenshot(path=str(tmp_path / f"{role}-actions-{width}.png"))
            if role == "surgeon":
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
                await native.screenshot(path=str(tmp_path / f"{role}-native-{width}.png"))
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
    }


@pytest.mark.asyncio
async def test_patient_node_workflow_and_metrics(tmp_path):
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
            await page.screenshot(path=str(tmp_path / "patient-overview.png"))
            await page.get_by_role("link", name="Nodes", exact=False).first.click()
            await expect(page.get_by_role("heading", name="Nodes", exact=True)).to_be_visible()
            await page.screenshot(path=str(tmp_path / "patient-nodes.png"))
            await (
                page.locator("#nodes .device")
                .filter(has_text="Thor")
                .get_by_role("link", name="Open node")
                .click()
            )
            await expect(page.locator("#node-name")).to_have_text("Thor")
            await expect(page.locator("#cameras")).not_to_contain_text("Room camera")
            await page.get_by_role("button", name="Deployment logs", exact=True).click()
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
            await page.get_by_role("button", name="Stream all", exact=True).click()
            await expect(page.get_by_role("button", name="Stop all", exact=True)).to_be_enabled()
            assert actions[-1] == {"action": "camera.start", "params": {"id": "thor:camera"}}
            assert await page.evaluate("window.offers") == 0
            await page.get_by_role("button", name="Preview", exact=True).click()
            await page.wait_for_function("window.offers === 1")
            await page.screenshot(path=str(tmp_path / "patient-node.png"))
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
            await page.screenshot(path=str(tmp_path / "patient-surgeons.png"))
            await page.goto("http://localhost:8777/#node/thor")
            await page.locator("#cameras").get_by_role("button", name="Metrics", exact=True).click()
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
            await page.screenshot(path=str(tmp_path / "patient-mobile.png"), full_page=True)
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_surgeon_arranges_views_without_reconnecting_or_switching_controls(tmp_path):
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
                    "status": "online",
                    "owner": None,
                }
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
            await page.screenshot(path=str(tmp_path / "surgeon-workspace.png"))
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
            await page.screenshot(path=str(tmp_path / "surgeon-feed-picker.png"))
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
            await page.reload()
            await expect(page.locator("#view-layout")).to_have_value("two")
            await expect(page.locator('[data-camera="thor:camera"]')).to_have_css("order", "0")
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.screenshot(path=str(tmp_path / "surgeon-mobile.png"), full_page=True)
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            state["session"]["robot"] = False
            await expect(page.locator("#robots-panel")).to_be_hidden()
            await expect(page.locator("#operating-workspace")).not_to_have_class("has-robot")
            await page.get_by_role("button", name="Hide all", exact=True).click()
            await expect(page.locator("video")).to_have_count(0)
            assert all(c["status"] == "live" for c in cameras)
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("robot_count", [1, 3])
async def test_patient_previews_do_not_move_robot_column(tmp_path, robot_count):
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
            await expect(page.locator("#node-name")).to_have_text("Host · Operating room")
            await expect(page.get_by_role("button", name="Add node", exact=True)).to_be_visible()
            assert await page.locator("#node-search").count() == 0
            await expect(page.get_by_role("link", name="← All nodes")).not_to_be_visible()
            await page.get_by_role("link", name="Overview", exact=True).click()
            await expect(page.locator("#device-workspace")).not_to_be_visible()
            await page.get_by_role("link", name="Nodes", exact=False).first.click()
            await expect(page.locator("#robots .robot")).to_have_count(robot_count)
            panel = page.locator("#robots-panel")
            baseline = await panel.bounding_box()
            cameras = await page.locator("#camera-panel").bounding_box()
            assert baseline["y"] == pytest.approx(cameras["y"], abs=1)
            assert baseline["x"] > cameras["x"] + cameras["width"]
            camera_heading = await page.locator("#camera-panel h2").bounding_box()
            robot_heading = await page.locator("#robots-panel h2").bounding_box()
            assert robot_heading["y"] == pytest.approx(camera_heading["y"], abs=1)

            async def stable():
                await page.evaluate("window.scrollTo(0, 0)")
                current = await panel.bounding_box()
                for key in ("x", "y", "width", "height"):
                    assert current[key] == pytest.approx(baseline[key], abs=1)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            await page.screenshot(path=str(tmp_path / "before-previews.png"))
            for count in (1, 2):
                await page.get_by_role("button", name="Preview", exact=True).first.click()
                await expect(page.locator("video")).to_have_count(count)
                await stable()
            await page.screenshot(path=str(tmp_path / "with-previews.png"), full_page=True)
            await page.locator(".video-tile").first.get_by_role("button", name="Enlarge").click()
            await stable()
            assert await page.evaluate("window.offers") == 2
            assert await page.evaluate("window.closedPeers") == 0

            state["cameras"].extend(camera_item(i) for i in range(3, 7))
            await expect(page.locator("#cameras .device")).to_have_count(6)
            await stable()
            await page.screenshot(path=str(tmp_path / "many-devices.png"))
            for width in (1280, 1024, 390):
                await page.set_viewport_size({"width": width, "height": 900})
                await page.evaluate("window.scrollTo(0, 0)")
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                robot = await panel.bounding_box()
                camera_panel = await page.locator("#camera-panel").bounding_box()
                preview = await page.locator("#views-panel").bounding_box()
                if width > 1050:
                    assert robot["y"] == pytest.approx(camera_panel["y"], abs=1)
                else:
                    assert camera_panel["y"] + camera_panel["height"] <= robot["y"]
                    assert robot["y"] + robot["height"] <= preview["y"]
                await page.screenshot(path=str(tmp_path / f"devices-{width}.png"), full_page=True)
            await page.set_viewport_size({"width": 1600, "height": 1000})
            for _ in range(2):
                await page.get_by_role("button", name="Hide preview", exact=True).first.click()
            await expect(page.locator("video")).to_have_count(0)
            await stable()
            assert not errors
        finally:
            await browser.close()
