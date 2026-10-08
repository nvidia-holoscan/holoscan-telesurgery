# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Delayed control replies must not create overlapping motion or retain a blurred tab's lock."""

import asyncio
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
@pytest.mark.parametrize("input_mode", ["pointer", "keyboard"])
async def test_motion_repress_and_blur_with_request_in_flight(input_mode):
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    calls = []
    state = {
        "role": "surgeon",
        "sdk": "test",
        "selected": [],
        "session": {
            "id": "surgeon",
            "status": "approved",
            "robot": True,
            "cameras": [],
            "robots": [
                {
                    "id": "host:robot",
                    "name": "Fixture",
                    "kind": "franka-sim",
                    "simulation": True,
                    "controls": {"inputs": ["buttons", "gamepad"], "groups": {"joints": 7}},
                    "owner": None,
                    "status": "online",
                }
            ],
        },
    }

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        elif path == "api/action":
            action = json.loads(request.request.post_data)["action"]
            calls.append(action)
            if action == "robot.move":
                await asyncio.sleep(0.25)
            await request.fulfill(json={"result": True})
        else:
            file = static / (path.removeprefix("static/") or "index.html")
            await request.fulfill(path=file)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.context.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            control = page.get_by_role("button", name="Fixture joints 1 increase (Q)", exact=True)

            await control.focus()
            await page.wait_for_timeout(1200)
            assert await control.evaluate("element => document.activeElement === element")

            async def press():
                if input_mode == "pointer":
                    await control.hover()
                    await page.mouse.down()
                else:
                    await page.locator(".keyboard-controls").focus()
                    await page.keyboard.down("q")

            async def release():
                if input_mode == "pointer":
                    await page.mouse.up()
                else:
                    await page.keyboard.up("q")

            await press()
            await page.wait_for_timeout(30)
            await release()
            await press()
            await page.wait_for_timeout(350)
            await release()
            assert calls.count("robot.move") == 1

            await page.reload()
            calls.clear()
            await press()
            await page.wait_for_timeout(30)
            await page.evaluate("window.dispatchEvent(new Event('blur'))")
            await release()
            await page.wait_for_timeout(700)
            assert calls.count("robot.move") == 1
            assert "robot.release" in calls
            assert "robot.renew" not in calls
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("codec", ["h264", "h265", "nvjpeg"])
async def test_holoviz_selection_bypasses_webrtc_and_switches_back(codec):
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    state = {
        "role": "surgeon",
        "sdk": "test",
        "selected": [],
        "native_views": {},
        "session": {
            "status": "approved",
            "robot": False,
            "robots": [],
            "cameras": [
                {
                    "id": "host:camera",
                    "name": "Room camera",
                    "kind": "fixture",
                    "codec": codec,
                    "width": 320,
                    "height": 240,
                    "status": "live",
                }
            ],
        },
    }
    offers = []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            assert body["params"]["camera"] == "host:camera"
            if body["action"] == "view.holoviz":
                state["selected"] = ["host:camera"]
                state["native_views"] = {"host:camera": {"status": "running"}}
            elif body["action"] == "view.browser":
                state["native_views"] = {}
            elif body["action"] == "view.close":
                state["native_views"] = {}
                state["selected"] = []
            else:
                pytest.fail(f"Unexpected action {body['action']}")
            await request.fulfill(json={"result": True})
        elif path == "api/offer":
            offers.append(request.request.post_data)
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.add_init_script("""window.RTCPeerConnection=class {
                constructor(){this.iceGatheringState='complete'}
                addTransceiver(){return {setCodecPreferences(){}}}
                createDataChannel(){return {readyState:'connecting',bufferedAmount:0,send(){}}}
                async createOffer(){return {type:'offer',sdp:'test'}}
                async setLocalDescription(d){this.localDescription=d}
                async setRemoteDescription(){}
                close(){}
            }""")
            await page.context.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.get_by_role("button", name="Add feeds", exact=True).first.click()
            await page.get_by_role("button", name="Open in Holoviz", exact=True).click()
            if codec != "h264":
                close = page.locator("#feed-dialog").get_by_role(
                    "button", name="Close Holoviz", exact=True
                )
                await close.wait_for()
                assert await page.locator("video").count() == 0
                assert not offers
                await close.click()
                await (
                    page.locator("#feed-dialog")
                    .get_by_role("button", name="Open in Holoviz", exact=True)
                    .wait_for()
                )
                assert not offers
                return
            await (
                page.locator("#feed-dialog")
                .get_by_role("button", name="Show in browser", exact=True)
                .wait_for()
            )
            assert await page.locator("video").count() == 0
            assert not offers
            await (
                page.locator("#feed-dialog")
                .get_by_role("button", name="Show in browser", exact=True)
                .click()
            )
            await page.wait_for_function("document.querySelectorAll('video').length === 1")
            async with asyncio.timeout(3):
                while not offers:
                    await asyncio.sleep(0.01)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_stream_metrics_inline_interval_statistics_and_closed_polling():
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    sample = {"count": 1000, "window_count": 1000, "p50": 1, "p95": 2, "p99": 3, "p99_9": 4}
    video = {
        "frames": 100,
        "last_frame_age_ms": 8,
        "sequence_gaps": 0,
        "sequence_resets": 0,
        "steady_metrics": {"encode_ms": sample, "receive_interval_ms": sample},
    }
    state = {
        "role": "surgeon",
        "sdk": "test",
        "selected": ["room"],
        "native_views": {},
        "timings": {"patient_round_trip_ms": sample, "control_ack_ms": {"count": 0}},
        "video": {"room": video},
        "session": {
            "id": "test",
            "status": "approved",
            "robot": False,
            "robots": [],
            "cameras": [{"id": "room", "name": "Room camera", "status": "live"}],
        },
    }
    requests, actions = [], []

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            if "metrics=1" in path:
                requests.append(asyncio.get_running_loop().time())
                video["frames"] += 150
            await request.fulfill(json=state)
        elif path == "api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            actions.append(body["action"])
            assert body["action"] == "metrics.reset"
            video["steady_metrics"] = {}
            await request.fulfill(json={"result": True})
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.add_init_script("""window.statsCalls=0; window.RTCPeerConnection=class {
                constructor(){this.iceGatheringState='complete'}
                addTransceiver(){return {setCodecPreferences(){}}}
                createDataChannel(){return {readyState:'connecting',bufferedAmount:0,send(){}}}
                async createOffer(){return {type:'offer',sdp:'test'}}
                async setLocalDescription(d){this.localDescription=d}
                async setRemoteDescription(){}
                close(){}
                async getStats(){
                    const n=window.statsCalls++;
                    return new Map([['video', {id:'video', type:'inbound-rtp', kind:'video',
                        timestamp:1000+5000*n, framesDecoded:100+150*n,
                        totalDecodeTime:1+0.15*n, jitterBufferDelay:2+0.9*n,
                        jitterBufferEmittedCount:100+150*n, framesDropped:n, packetsLost:n,
                        freezeCount:n, transportId:'transport'}],
                        ['transport', {selectedCandidatePairId:'pair'}],
                        ['pair', {currentRoundTripTime:0.001}]]);
                }
            }""")
            await page.context.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await page.wait_for_timeout(1200)
            assert not requests and await page.evaluate("window.statsCalls") == 0
            await (
                page.locator(".video-tile")
                .get_by_role("button", name="Metrics", exact=True)
                .click()
            )
            metrics = page
            assert len(page.context.pages) == 1
            await expect(page.locator("#metrics-title")).to_have_text("Room camera")
            await expect(page.locator("#metrics-camera")).not_to_be_visible()
            output = metrics.locator("#report-output")
            await expect(output).to_contain_text("Collecting interval statistics")
            assert await metrics.locator("#report-interval").input_value() == "5000"
            pipeline = output.get_by_role("table", name="Latency breakdown, in milliseconds")
            await expect(
                pipeline.locator("tr")
                .filter(has=page.get_by_role("rowheader", name="Encode", exact=False))
                .last
            ).to_contain_text("4.00")
            await expect(output.locator(".metrics-notes")).not_to_have_attribute("open", "")
            await page.wait_for_timeout(1200)
            assert len(requests) == 1
            await metrics.locator("#report-interval").select_option("1000")
            await expect(output.locator("#metrics-buffer")).to_have_text("6.00 ms", timeout=6000)
            await expect(output.locator("#metrics-decode")).to_have_text("1.00 ms")
            await expect(output.locator('[data-card="fps"] strong')).to_have_text("30.00")
            assert requests[1] - requests[0] >= 1.1
            await page.wait_for_function("window.statsCalls >= 3")
            assert 0.9 <= requests[2] - requests[1] < 3
            await expect(output.locator("#metrics-browser-counters dd").first).to_have_text("2")
            await expect(output.locator('[data-card="fps"] path')).not_to_have_attribute("d", "")
            await metrics.get_by_role("button", name="Reset metrics", exact=True).click()
            await expect(
                pipeline.locator("tr")
                .filter(has=page.get_by_role("rowheader", name="Encode", exact=False))
                .last
            ).to_contain_text("Collecting samples")
            await expect(output).to_contain_text("Collecting interval statistics")
            await expect(output.locator("#metrics-browser-counters dd").first).to_have_text("0")
            await expect(output.locator('[data-card="fps"] path')).to_have_attribute("d", "")
            assert actions == ["metrics.reset"]
            await metrics.locator("#close-metrics").click()
            closed = len(requests)
            await page.wait_for_timeout(1500)
            assert len(requests) == closed and await page.evaluate("window.statsCalls") == closed
            await (
                page.locator(".video-tile")
                .get_by_role("button", name="Metrics", exact=True)
                .click()
            )
            await expect(metrics.locator("#report-output")).to_contain_text(
                "Collecting interval statistics"
            )
            await metrics.locator("#close-metrics").click()
        finally:
            await browser.close()
