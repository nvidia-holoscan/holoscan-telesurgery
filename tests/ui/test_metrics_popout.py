# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Moving metrics between windows retains timing and does not reconnect video."""

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import Error, async_playwright, expect
from telesurgery.server.security import security_headers


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["patient", "surgeon"])
async def test_metrics_popout_dock_close_and_blocked_popup(role, tmp_path):
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    camera = {
        "id": "host:room",
        "node": "host",
        "name": "Room camera",
        "kind": "USB",
        "status": "live",
        "codec": "h264",
        "width": 640,
        "height": 480,
        "fps": 60,
    }
    sample = {"count": 1000, "window_count": 1000, "p50": 1, "p95": 2, "p99": 3, "p99_9": 4}
    state = {
        "role": role,
        "sdk": "5",
        "endpoint_port": 7447,
        "nodes": [{"id": "host", "name": "Workstation", "status": "online"}],
        "cameras": [camera],
        "robots": [],
        "surgeons": [],
        "selected": [camera["id"]],
        "native_views": {},
        "session": {"id": "test", "status": "approved", "cameras": [camera], "robots": []},
        "video": {camera["id"]: {"frames": 100, "steady_metrics": {"encode_ms": sample}}},
    }
    requests, actions, errors = [], [], []

    async def route(request):
        path = str(request.rel_url).lstrip("/")
        if path.startswith("api/status"):
            if "metrics=1" in path:
                requests.append(path)
                assert "device=host%3Aroom" in path
            return web.json_response(state)
        elif path == "api/offer":
            return web.json_response({"sdp": "test", "type": "answer"})
        elif path == "api/action":
            actions.append(await request.json())
            return web.json_response({"result": True})
        else:
            pytest.fail(f"Unexpected request: {path}")

    async def index(request):
        return web.FileResponse(static / "index.html")

    app = web.Application()
    app.on_response_prepare.append(security_headers)
    app.router.add_get("/", index)
    app.router.add_route("*", "/api/{name}", route)
    app.router.add_static("/static/", static)
    async with TestServer(app) as server, async_playwright() as p:
        url = str(server.make_url("/"))
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.add_init_script("""window.offers=0; window.closedPeers=0;
                window.RTCPeerConnection=class {
                    constructor(){this.iceGatheringState='complete'}
                    addTransceiver(){return {setCodecPreferences(){}}}
                    createDataChannel(){return {readyState:'connecting',bufferedAmount:0,send(){}}}
                    async createOffer(){window.offers++;return {type:'offer',sdp:'test'}}
                    async setLocalDescription(d){this.localDescription=d}
                    async setRemoteDescription(){}
                    async getStats(){return new Map()}
                    close(){window.closedPeers++}
                };""")
            await page.goto(url)
            if role == "patient":
                await page.get_by_role("button", name="Preview", exact=True).click()
            await expect(page.locator("video")).to_have_count(1)
            open_metrics = page.locator(".video-tile").get_by_role(
                "button", name="Metrics", exact=True
            )
            await open_metrics.click()
            await page.locator("#report-interval").select_option("1000")
            await page.get_by_label("Latency history window").select_option("60")
            await expect(page.locator('[data-card="encode"] h3')).to_have_text("Encode · P99")
            await expect(page.locator('[data-card="encode"] strong')).to_have_text("3.00")
            await page.locator('[data-card="encode"] strong').evaluate(
                "node => node.ownerDocument.getSelection().selectAllChildren(node)"
            )
            sample["p99"] = 7
            await expect(page.locator("#metrics-updated")).to_have_text(
                "Updates paused while text is selected"
            )
            assert await page.evaluate("getSelection().toString()") == "3.00"
            await page.evaluate("getSelection().removeAllRanges()")
            await expect(page.locator('[data-card="encode"] strong')).to_have_text("7.00")
            encode_row = page.locator("#metrics-pipeline tr").filter(
                has=page.get_by_role("rowheader", name="Encode", exact=False)
            )
            await expect(encode_row.locator("td").nth(0)).to_have_css("font-weight", "400")
            await expect(encode_row.locator("td").nth(2)).to_have_css("font-weight", "600")
            header = page.locator(".metrics-sheet-heading")
            for name in ("Pop out", "Close"):
                control = header.get_by_role("button", name=name, exact=True)
                await expect(control).to_have_attribute("title", name)
                await expect(control.locator("svg")).to_be_visible()
            boxes = [
                await header.get_by_role("button", name=name).bounding_box()
                for name in ("Pop out", "Close")
            ]
            assert boxes[0]["y"] == boxes[1]["y"]
            await header.locator("h2").click()
            await expect(page.locator("#metrics-page")).to_be_visible()
            await page.screenshot(path=str(tmp_path / "metrics-inline.png"))

            async with page.expect_popup() as opening:
                await page.get_by_role("button", name="Pop out", exact=True).click()
            popup = await opening.value
            popup.on("pageerror", lambda error: errors.append(str(error)))
            await expect(popup.locator("#metrics-title")).to_have_text("Room camera")
            await expect(popup.locator(".metrics-sheet")).to_have_css("position", "fixed")
            await expect(popup.locator(".metrics-heading-actions")).to_have_css("display", "flex")
            await expect(popup.get_by_role("button", name="Dock", exact=True)).to_have_attribute(
                "title", "Dock"
            )
            await expect(page.locator("#metrics-backdrop")).to_be_hidden()
            assert not await page.locator(".app-shell").evaluate("node => node.inert")
            assert await popup.locator("#report-interval").input_value() == "1000"
            assert await popup.get_by_label("Latency history window").input_value() == "60"
            assert await page.locator("#metrics-page").count() == 0
            assert await page.evaluate("window.offers") == 1
            assert await page.evaluate("window.closedPeers") == 0
            await popup.screenshot(path=str(tmp_path / "metrics-popout.png"))
            before = len(requests)
            # Hiding the dashboard must not stop a visible pop-out's sampler.
            await page.evaluate("""Object.defineProperty(document, 'hidden', {
                    configurable:true, get:()=>true});
                document.dispatchEvent(new Event('visibilitychange'));""")
            await popup.wait_for_timeout(2200)
            assert 1 <= len(requests) - before <= 3
            await popup.get_by_role("button", name="Reset metrics", exact=True).click()
            assert actions[-1] == {"action": "metrics.reset", "params": {"device": camera["id"]}}
            await page.evaluate("delete document.hidden")
            async with popup.expect_event("close"):
                try:
                    await popup.get_by_role("button", name="Dock", exact=True).click()
                except Error:
                    # Dock moves the button to the opener and can close the popup
                    # before Playwright receives the click acknowledgement.
                    if not popup.is_closed():
                        raise
            await expect(page.locator("#metrics-page")).to_be_visible()
            assert await page.locator("#report-interval").input_value() == "1000"
            assert await page.get_by_label("Latency history window").input_value() == "60"
            assert popup.is_closed()
            await expect(page.locator("#metrics-backdrop")).to_be_visible()
            assert await page.locator(".app-shell").evaluate("node => node.inert")
            before = len(requests)
            await page.mouse.click(10, 100)
            await expect(page.locator("#metrics-page")).to_be_hidden()
            await expect(page.locator("#metrics-backdrop")).to_be_hidden()
            await expect(open_metrics).to_be_focused()
            assert not await page.locator(".app-shell").evaluate("node => node.inert")
            await page.wait_for_timeout(1200)
            assert len(requests) == before
            assert len(actions) == 1  # Dismissal never activates underlying controls.
            await open_metrics.click()

            async with page.expect_popup() as reopening:
                await page.get_by_role("button", name="Pop out", exact=True).click()
            popup = await reopening.value
            await expect(popup.locator("#metrics-title")).to_be_visible()
            await popup.close()  # Window-manager close must stop polling and restore the panel.
            await expect(page.locator("#metrics-page")).to_be_hidden()
            before = len(requests)
            await page.wait_for_timeout(1200)
            assert len(requests) == before
            await open_metrics.click()
            await page.evaluate("window.open = () => null")
            await page.get_by_role("button", name="Pop out", exact=True).click()
            await expect(page.locator("#notice")).to_contain_text("Allow pop-ups")
            await expect(page.locator("#metrics-page")).to_be_visible()
            await page.locator("#close-metrics").click()
            assert await page.evaluate("window.offers") == 1
            assert await page.evaluate("window.closedPeers") == 0
            assert not errors
        finally:
            await browser.close()
