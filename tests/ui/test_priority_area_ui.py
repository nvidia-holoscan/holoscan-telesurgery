# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A surgeon draws a priority area on the picture; every viewer sees its outline."""

import asyncio
import json
import math
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
import pytest
from playwright.async_api import async_playwright, expect

STATIC = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
PEER = """window.RTCPeerConnection=class {
 constructor(){this.iceGatheringState='complete'}
 addTransceiver(){return {setCodecPreferences(){}}}
 createDataChannel(){return {readyState:'connecting',bufferedAmount:0,send(){}}}
 async createOffer(){return {type:'offer',sdp:'test'}}
 async setLocalDescription(d){this.localDescription=d}
 async setRemoteDescription(){} close(){}
 async getStats(){return new Map()}
};"""
FIELDS = ("region_supported", "region_unavailable", "region", "region_by")
BOX = [[0.3, 0.25], [0.7, 0.25], [0.7, 0.75], [0.3, 0.75]]
VIDEO, STILL = ".video-tile video", ".region-still-stage"
# What a Holoviz window lends the dashboard: a small JPEG of its picture.
JPEG = cv2.imencode(".jpg", np.full((360, 640, 3), (60, 70, 150), dtype=np.uint8))[1].tobytes()


def camera(**changes):
    return {
        "id": "room:scope",
        "node": "room",
        "name": "Endoscope",
        "kind": "USB",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "status": "live",
        "codec": "h264",
        "region_supported": True,
        "region_unavailable": "",
        "region": None,
        "region_by": "",
        **changes,
    }


def surgeon(cameras, *, robot=True, native=()):
    return {
        "role": "surgeon",
        "sdk": "5.0",
        "patient": "127.0.0.1:7447",
        "selected": [item["id"] for item in cameras],
        "native_views": {key: {"status": "running"} for key in native},
        "session": {
            "id": "one",
            "status": "approved",
            "robot": robot,
            "cameras": cameras,
            "robots": [],
        },
    }


@asynccontextmanager
async def dashboard(state, *, size=(1440, 900), refuse=None, ready=".video-tile, .native-tile"):
    """The real page against a stand-in server that keeps the camera's area."""
    actions, errors = [], []
    cameras = state["session"]["cameras"] if state["role"] == "surgeon" else state["cameras"]

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path.startswith("api/status"):
            await request.fulfill(json=state)
        elif "/native-preview" in path:
            # Recorded with the actions, so tests can tell when the page stops asking.
            identity = path.removeprefix("api/cameras/").split("/native-preview")[0]
            actions.append({"action": "native-preview", "params": {"id": identity}})
            if identity.replace("%3A", ":") not in state["native_views"]:
                return await request.fulfill(status=404, json={"error": "Not open in Holoviz"})
            await request.fulfill(status=200, content_type="image/jpeg", body=JPEG)
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            actions.append(body)
            if refuse and body["action"] in refuse:
                return await request.fulfill(status=400, json={"error": refuse[body["action"]]})
            if body["action"] != "camera.region":
                return await request.fulfill(json={"result": True})
            item = next(c for c in cameras if c["id"] == body["params"]["id"])
            item["region"] = body["params"]["points"]
            item["region_by"] = "Dr. Rivera" if item["region"] else ""
            await request.fulfill(json={"result": {key: item[key] for key in FIELDS}})
        elif path == "api/offer":
            await request.fulfill(json={"sdp": "test", "type": "answer"})
        else:
            await request.fulfill(path=STATIC / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": size[0], "height": size[1]})
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.add_init_script(PEER)
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/")
            await expect(page.locator(ready).first).to_be_visible()
            yield page, actions, errors
            assert not errors
        finally:
            await browser.close()


async def picture(page, target=VIDEO):
    """The picture's box on screen, once the view has sized it."""
    await page.wait_for_function(
        "target => document.querySelector(target)?.getBoundingClientRect().width > 0",
        arg=target,
    )
    return await page.locator(target).first.bounding_box()


async def drag(page, start, end, *, steps=8, target=VIDEO):
    """Press at one point of the picture and release at another (fractions of the picture)."""
    frame = await picture(page, target)
    await page.mouse.move(
        frame["x"] + frame["width"] * start[0], frame["y"] + frame["height"] * start[1]
    )
    await page.mouse.down()
    await page.mouse.move(
        frame["x"] + frame["width"] * end[0], frame["y"] + frame["height"] * end[1], steps=steps
    )
    await page.mouse.up()


async def outline(page, target=VIDEO):
    """The drawn outline's extent as fractions of the picture: left, top, right, bottom."""
    await picture(page, target)
    return await page.evaluate(
        """target => {
            const picture = document.querySelector(target);
            const frame = picture.getBoundingClientRect();
            const line = picture.parentElement.querySelector('.region-line')
                .getBoundingClientRect();
            return [(line.left - frame.left) / frame.width, (line.top - frame.top) / frame.height,
                (line.right - frame.left) / frame.width, (line.bottom - frame.top) / frame.height];
        }""",
        target,
    )


async def settled(page):
    """Let the page finish laying out after its window changed size."""
    await page.evaluate("() => new Promise(r => requestAnimationFrame(() => setTimeout(r, 50)))")


def regions(actions):
    return [a["params"] for a in actions if a["action"] == "camera.region"]


def stills(actions):
    return sum(a["action"] == "native-preview" for a in actions)


def zooms(actions):
    return [a["params"] for a in actions if a["action"] == "view.zoom"]


async def eventually(page, check, timeout=3000):
    """Wait for something the page does shortly after, such as a debounced request."""
    for _ in range(timeout // 50):
        if check():
            return
        await page.wait_for_timeout(50)
    assert check()


async def in_view(page):
    """The outline's box within the visible view, as fractions: left, top, right, bottom."""
    return await page.evaluate(
        """() => {
            const view = document.querySelector('.view-viewport').getBoundingClientRect();
            const line = document.querySelector('.region-line').getBoundingClientRect();
            return [(line.left - view.left) / view.width, (line.top - view.top) / view.height,
                (line.right - view.left) / view.width, (line.bottom - view.top) / view.height];
        }"""
    )


def framing(width, height):
    """The zoom label once a new area of this size (fractions of the view) is framed."""
    scale = min(4, max(1, math.floor(0.8 / max(width, height) * 20 + 1e-6) / 20))
    return f"{round(scale, 2):g}×"


@pytest.mark.asyncio
async def test_controlling_surgeon_draws_a_box_or_a_lasso_and_clears_it():
    state = surgeon([camera()])
    async with dashboard(state) as (page, actions, _):
        tools = page.get_by_role("group", name="Endoscope priority area")
        box = tools.get_by_role("button", name="Draw a box")
        lasso = tools.get_by_role("button", name="Draw freehand")
        clear = tools.get_by_role("button", name="Clear priority area")
        level = page.locator(".zoom-level")
        await expect(tools).to_be_visible()
        # One bar on the picture: the area tools lead the zoom controls, without a text label.
        bar = page.get_by_role("group", name="Endoscope view tools")
        assert await page.locator(".view-surface > .view-zoom").count() == 1
        assert await page.locator(".view-surface > .view-region").count() == 0
        assert await bar.get_by_role("button").all_inner_texts() == [
            "Draw a box",
            "Draw freehand",
            "Zoom out",
            "1×",
            "Zoom in",
        ]
        assert await tools.locator(":scope > :not(button)").count() == 0
        await expect(page.get_by_text("Priority area", exact=True)).to_have_count(0)
        await expect(box).to_be_enabled()
        await expect(lasso).to_be_enabled()
        await expect(clear).to_be_hidden()  # nothing to clear yet
        idle = [await box.bounding_box(), await lasso.bounding_box()]
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(page.locator(".region-status")).to_be_hidden()
        # An unarmed drag on the picture draws nothing.
        await drag(page, (0.3, 0.25), (0.7, 0.75))
        assert regions(actions) == []

        # One click arms the tool; one drag draws and sends the area.
        await box.click()
        await expect(box).to_have_attribute("aria-pressed", "true")
        await expect(page.locator(".region-instruction")).to_have_text(
            "Drag a box around the area · Esc to cancel"
        )
        assert await page.locator(".view-viewport").evaluate("e => getComputedStyle(e).cursor") == (
            "crosshair"
        )
        await drag(page, (0.3, 0.25), (0.7, 0.75))
        await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "active")
        sent = regions(actions)
        assert len(sent) == 1 and sent[0]["id"] == "room:scope"
        for point, expected in zip(sent[0]["points"], BOX, strict=True):
            assert point == pytest.approx(expected, abs=0.004)
        assert await outline(page) == pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.004)
        # The tool disarms after one area, and everyone is told what the outline means.
        await expect(box).to_have_attribute("aria-pressed", "false")
        await expect(page.locator(".region-instruction")).to_be_hidden()
        await expect(clear).to_be_enabled()
        await expect(page.locator(".region-status")).to_have_text(
            "Priority area set by Dr. Rivera: picture detail is concentrated inside the outline."
        )
        # Clear joins the bar at its far end, so the drawing tools stay where they were.
        assert await bar.get_by_role("button").all_inner_texts() == [
            "Clear priority area",
            "Draw a box",
            "Draw freehand",
            "Zoom out",
            framing(0.4, 0.5),
            "Zoom in",
        ]
        assert [await box.bounding_box(), await lasso.bounding_box()] == idle
        # The viewer's own area now fills most of their view.
        await expect(level).to_have_text(framing(0.4, 0.5))
        assert await in_view(page) == pytest.approx([0.18, 0.1, 0.82, 0.9], abs=0.01)

        # Freehand: one stroke around the structure, closed and simplified for the encoder.
        await lasso.click()
        await expect(page.locator(".region-instruction")).to_have_text(
            "Draw around the area · Esc to cancel"
        )
        frame = await picture(page)
        centre = (frame["x"] + frame["width"] * 0.6, frame["y"] + frame["height"] * 0.5)
        radius = frame["height"] * 0.3
        await page.mouse.move(centre[0] + radius, centre[1])
        await page.mouse.down()
        for step in range(1, 181):
            angle = math.radians(step * 2)
            await page.mouse.move(
                centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)
            )
        await page.mouse.up()
        await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "active")
        sent = regions(actions)
        assert len(sent) == 2
        points = sent[1]["points"]
        assert 12 <= len(points) <= 64
        for x, y in points:  # every kept point lies on the drawn circle
            distance = math.hypot((x - 0.6) * frame["width"], (y - 0.5) * frame["height"])
            assert distance == pytest.approx(radius, abs=2)
        assert await outline(page) == pytest.approx(
            [0.6 - radius / frame["width"], 0.2, 0.6 + radius / frame["width"], 0.8], abs=0.01
        )
        await expect(level).to_have_text(framing(2 * radius / frame["width"], 0.6))

        # One click clears it for everyone, and the view returns to where it was.
        await clear.click()
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(page.locator(".region-status")).to_be_hidden()
        await expect(clear).to_be_hidden()
        await expect(level).to_have_text("1×")
        assert regions(actions)[2] == {"id": "room:scope", "points": None}
        assert state["session"]["cameras"][0]["region"] is None


@pytest.mark.asyncio
async def test_escape_cancels_and_slips_are_not_sent():
    state = surgeon([camera()])
    async with dashboard(state) as (page, actions, _):
        box = page.get_by_role("button", name="Draw a box")
        lasso = page.get_by_role("button", name="Draw freehand")
        # Keyboard: the tools are reachable and show focus; Enter arms, Esc cancels and returns.
        await box.focus()
        await page.keyboard.press("Enter")
        await expect(box).to_have_attribute("aria-pressed", "true")
        await page.keyboard.press("Escape")
        await expect(box).to_have_attribute("aria-pressed", "false")
        await expect(box).to_be_focused()
        assert "solid" in await box.evaluate("e => getComputedStyle(e).outlineStyle")
        await page.keyboard.press("Tab")
        await expect(lasso).to_be_focused()
        # The area tools come before zoom in the bar; Esc with nothing armed leaves focus alone.
        await page.keyboard.press("Escape")
        await expect(lasso).to_be_focused()
        await page.keyboard.press("Tab")  # Zoom out is disabled at 1×
        await expect(page.locator(".zoom-level")).to_be_focused()
        await page.keyboard.press("Shift+Tab")
        await expect(lasso).to_be_focused()

        # Esc in the middle of a stroke abandons it.
        await lasso.click()
        frame = await picture(page)
        await page.mouse.move(frame["x"] + 200, frame["y"] + 200)
        await page.mouse.down()
        await page.mouse.move(frame["x"] + 500, frame["y"] + 400, steps=6)
        await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "drawing")
        await page.keyboard.press("Escape")
        await page.mouse.up()
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(lasso).to_have_attribute("aria-pressed", "false")

        # Clicking the armed tool again disarms it; a click without a drag draws nothing.
        await box.click()
        await box.click()
        await expect(box).to_have_attribute("aria-pressed", "false")
        await box.click()
        await page.mouse.click(frame["x"] + 300, frame["y"] + 300)
        await expect(box).to_have_attribute("aria-pressed", "true")  # still armed for a real drag
        # A slip of a few pixels is not an area.
        await drag(page, (0.5, 0.5), (0.52, 0.53))
        await expect(page.locator("#notice")).to_have_text("Draw a larger priority area")
        await expect(page.locator(".region-overlay")).to_be_hidden()
        assert regions(actions) == []


@pytest.mark.asyncio
async def test_own_area_frames_the_view_and_its_end_returns_the_view():
    state = surgeon([camera()])
    scope = state["session"]["cameras"][0]
    async with dashboard(state) as (page, actions, _):
        level = page.locator(".zoom-level")
        box = page.get_by_role("button", name="Draw a box")
        clear = page.get_by_role("button", name="Clear priority area")
        zoom_in = page.get_by_role("button", name="Zoom in", exact=True)

        async def draw(start, end):
            sent = len(regions(actions))
            await box.click()
            await drag(page, start, end)
            await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "active")
            assert len(regions(actions)) == sent + 1

        async def sent_view(**expected):
            await eventually(
                page,
                lambda: (
                    zooms(actions)
                    and zooms(actions)[-1] == pytest.approx({"camera": "room:scope", **expected})
                ),
            )

        # The viewer starts from a view of their own.
        await zoom_in.click()
        await zoom_in.click()
        await expect(level).to_have_text("1.5×")
        # Their new area is centred and fills four fifths of the view (zoom stops at 4×).
        await draw((0.4, 0.3), (0.6, 0.5))
        await expect(level).to_have_text("4×")
        assert await in_view(page) == pytest.approx([0.1, 0.1, 0.9, 0.9], abs=0.01)
        await sent_view(scale=4, x=0.5, y=0.4)
        # A new area while framed is framed in turn...
        await draw((0.4, 0.3), (0.5, 0.4))
        await expect(level).to_have_text("4×")
        assert await in_view(page) == pytest.approx([0.3, 0.3, 0.7, 0.7], abs=0.01)
        await sent_view(scale=4, x=0.45, y=0.35)
        # ...and clearing returns to the view from before the first one. Clear leaves the bar,
        # so the keyboard moves to the first tool.
        await clear.focus()
        await page.keyboard.press("Enter")
        await expect(level).to_have_text("1.5×")
        await sent_view(scale=1.5, x=0.5, y=0.5)
        await expect(clear).to_be_hidden()
        await expect(box).to_be_focused()

        # A viewer who moved after the framing keeps the view they chose.
        await draw((0.3, 0.3), (0.7, 0.7))
        await expect(level).to_have_text("2×")
        await page.get_by_role("button", name="Zoom out", exact=True).click()
        await expect(level).to_have_text("1.75×")
        await clear.click()
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(level).to_have_text("1.75×")

        # Someone else clearing the area also returns the view.
        await draw((0.3, 0.3), (0.7, 0.7))
        await expect(level).to_have_text("2×")
        scope.update(region=None, region_by="")
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(level).to_have_text("1.75×")
        # Someone else's area never moves this view, when it appears or when it goes.
        scope.update(region=BOX, region_by="Dr. Chen")
        await expect(page.locator(".region-status")).to_contain_text("set by Dr. Chen")
        await expect(level).to_have_text("1.75×")
        scope.update(region=None, region_by="")
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(level).to_have_text("1.75×")


@pytest.mark.asyncio
async def test_a_redraw_from_an_earlier_status_does_not_undo_a_new_area():
    patient = {
        "role": "patient",
        "sdk": "5.0",
        "endpoint_port": 7447,
        "nodes": [{"id": "room", "name": "Operating room", "status": "online"}],
        "cameras": [camera(), camera(id="room:wide", name="Room camera")],
        "robots": [],
        "surgeons": [],
        "native_views": {},
    }
    async with dashboard(patient, ready="#equipment-rows tr") as (page, actions, _):
        preview = page.locator("#equipment-rows").get_by_role("button", name="Preview", exact=True)
        await preview.first.click()
        await expect(page.locator(".video-tile")).to_have_count(1)
        scope = page.locator(".video-tile").first
        # No newer status reaches the page until it is released.
        held = asyncio.Event()

        async def hold(route):
            await held.wait()
            await route.fallback()

        await page.route("http://localhost:8777/api/status", hold)
        await page.get_by_role("button", name="Draw a box").click()
        await drag(page, (0.3, 0.3), (0.7, 0.7))
        await expect(scope.locator(".region-overlay")).to_have_attribute("data-state", "active")
        await expect(scope.locator(".zoom-level")).to_have_text("2×")
        # Opening another preview redraws the page from the status fetched before the area.
        await preview.first.click()
        await expect(page.locator(".video-tile")).to_have_count(2)
        await page.wait_for_timeout(200)
        await expect(scope.locator(".region-overlay")).to_be_visible()
        await expect(scope.get_by_role("button", name="Clear priority area")).to_be_visible()
        await expect(scope.locator(".zoom-level")).to_have_text("2×")
        held.set()
        await page.wait_for_timeout(1200)
        await expect(scope.locator(".region-overlay")).to_be_visible()
        await expect(scope.locator(".zoom-level")).to_have_text("2×")
        assert len(regions(actions)) == 1


@pytest.mark.asyncio
async def test_view_only_session_sees_the_area_but_cannot_change_it():
    state = surgeon([camera(region=BOX, region_by="Dr. Rivera")], robot=False)
    async with dashboard(state) as (page, actions, _):
        tools = page.get_by_role("group", name="Endoscope priority area")
        await expect(tools).to_be_visible()
        for name in ("Draw a box", "Draw freehand", "Clear priority area"):
            control = tools.get_by_role("button", name=name)
            await expect(control).to_be_disabled()
            await expect(control).to_have_attribute(
                "title", "View-only access cannot change the priority area"
            )
        # The outline and its meaning are still shown.
        assert await outline(page) == pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.004)
        await expect(page.locator(".region-status")).to_have_text(
            "Priority area set by Dr. Rivera: picture detail is concentrated inside the outline."
        )
        await drag(page, (0.1, 0.1), (0.9, 0.9))
        assert regions(actions) == []
        # Another surgeon's change arrives with the next status. Nobody else's view moves.
        await expect(page.locator(".zoom-level")).to_have_text("1×")
        state["session"]["cameras"][0].update(region=None, region_by="")
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(page.locator(".region-status")).to_be_hidden()
        await expect(tools.get_by_role("button", name="Clear priority area")).to_be_hidden()
        await expect(page.locator(".zoom-level")).to_have_text("1×")
        assert zooms(actions) == []


@pytest.mark.asyncio
async def test_a_refused_area_is_explained_and_not_left_on_the_picture():
    state = surgeon([camera()])
    refusal = "View-only access cannot change the priority area"
    async with dashboard(state, refuse={"camera.region": refusal}) as (page, actions, _):
        await page.get_by_role("button", name="Draw a box").click()
        await drag(page, (0.3, 0.25), (0.7, 0.75))
        await expect(page.locator("#notice")).to_have_text(refusal)
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(page.locator(".region-status")).to_be_hidden()
        assert len(regions(actions)) == 1
        # An area that was not accepted does not move the view.
        await expect(page.locator(".zoom-level")).to_have_text("1×")
        assert zooms(actions) == []


@pytest.mark.asyncio
async def test_settings_that_prevent_an_area_disable_the_tools_with_the_reason():
    reason = "turn off adaptive quantization (aq, temporalaq) in the stream's advanced settings"
    state = surgeon([camera(region_unavailable=reason)])
    async with dashboard(state) as (page, actions, _):
        tools = page.get_by_role("group", name="Endoscope priority area")
        await expect(tools).to_be_visible()
        for name in ("Draw a box", "Draw freehand"):
            control = tools.get_by_role("button", name=name)
            await expect(control).to_be_disabled()
            await expect(control).to_have_attribute("title", f"Priority area unavailable: {reason}")
        await expect(tools.get_by_role("button", name="Clear priority area")).to_be_hidden()
        await expect(page.locator(".region-status")).to_have_text(
            f"Priority area unavailable: {reason}."
        )
        await drag(page, (0.3, 0.25), (0.7, 0.75))
        assert regions(actions) == []
        # Once the operator changes the stream, the tools work without a reload.
        state["session"]["cameras"][0]["region_unavailable"] = ""
        await expect(tools.get_by_role("button", name="Draw a box")).to_be_enabled()
        await expect(page.locator(".region-status")).to_be_hidden()


@pytest.mark.asyncio
@pytest.mark.parametrize("reported", ["unsupported", "older node"])
async def test_an_encoder_without_region_support_leaves_the_view_as_it_was(reported):
    """No controls, no outline and the same layout; view zoom keeps working."""
    plain = {key: value for key, value in camera().items() if key not in FIELDS}
    if reported == "unsupported":
        # Stale values must not surface when the encoder cannot use them.
        plain.update(region_supported=False, region_unavailable="unused", region=BOX)

    async def layout(page):
        return await page.evaluate(
            """() => ['.video-tile', '.view-surface', '.view-viewport', '.view-zoom .zoom-menu',
                      '.video-caption', '.video-caption .actions'].map(selector => {
                const box = document.querySelector(selector).getBoundingClientRect();
                return [selector, box.x, box.y, box.width, box.height];
            })"""
        )

    async def bar(page):
        return await page.locator(".view-zoom").bounding_box()

    async with dashboard(surgeon([plain])) as (page, actions, _):
        await expect(page.locator(".view-zoom")).to_be_visible()
        await expect(page.locator(".view-region")).to_be_hidden()
        await expect(page.locator(".region-overlay")).to_be_hidden()
        await expect(page.locator(".region-status")).to_be_hidden()
        await expect(page.locator(".region-instruction")).to_be_hidden()
        assert await page.get_by_role("button", name="Draw a box").count() == 0
        await expect(page.get_by_role("group", name="Endoscope view zoom")).to_be_visible()
        without, plain_bar = await layout(page), await bar(page)
        # The bar is the zoom group alone: 2 + 28 + 44 + 28 + 2 px and its border.
        assert plain_bar["width"] == pytest.approx(106, abs=1)
        # The existing surgeon-side view tools behave as before.
        await page.get_by_role("button", name="Zoom in", exact=True).click()
        await expect(page.locator(".zoom-level")).to_have_text("1.25×")
        await page.get_by_role("button", name="Zoom controls").click()
        await page.get_by_role("button", name="Select area").click()
        await drag(page, (0.25, 0.25), (0.75, 0.75))
        await expect(page.locator(".zoom-level")).to_have_text("2×")
        assert regions(actions) == []
    # The same camera with the tools: they lead the same bar, which grows to the left only.
    async with dashboard(surgeon([camera()])) as (page, _, _):
        await expect(page.locator(".view-zoom > .view-region")).to_be_visible()
        assert await layout(page) == without
        with_tools = await bar(page)
        assert with_tools["x"] + with_tools["width"] == plain_bar["x"] + plain_bar["width"]
        assert (with_tools["y"], with_tools["height"]) == (plain_bar["y"], plain_bar["height"])
        assert with_tools["width"] > plain_bar["width"]


@pytest.mark.asyncio
async def test_outline_and_drawing_follow_zoom_pan_resize_and_side_by_side_depth():
    state = surgeon([camera(region=BOX, region_by="Dr. Rivera", depth=True)])
    async with dashboard(state) as (page, actions, _):
        expected = pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.004)
        assert await outline(page) == expected

        async def stroke():
            return await page.locator(".region-line").evaluate(
                """line => parseFloat(getComputedStyle(line).strokeWidth)
                    * line.closest('.depth-stage').getBoundingClientRect().width
                    / line.closest('.depth-stage').clientWidth"""
            )

        assert await stroke() == pytest.approx(2, abs=0.05)
        # Zoomed and panned, the outline stays on the same part of the picture.
        zoom_in = page.get_by_role("button", name="Zoom in", exact=True)
        for _ in range(4):
            await zoom_in.click()
        await expect(page.locator(".zoom-level")).to_have_text("2×")
        viewport = await page.locator(".view-viewport").bounding_box()
        frame = await picture(page)
        assert frame["width"] == pytest.approx(viewport["width"] * 2, abs=1)
        assert await outline(page) == expected
        assert await stroke() == pytest.approx(2, abs=0.05)  # same width on screen
        await page.mouse.move(viewport["x"] + 400, viewport["y"] + 300)
        await page.mouse.down()
        await page.mouse.move(viewport["x"] + 250, viewport["y"] + 200, steps=5)
        await page.mouse.up()
        moved = await picture(page)
        assert moved["x"] == pytest.approx(frame["x"] - 150, abs=1)
        assert await outline(page) == expected

        # Drawing while zoomed targets the picture, and the armed tool, not pan, gets the drag.
        await page.get_by_role("button", name="Draw a box").click()
        await page.mouse.move(viewport["x"] + 100, viewport["y"] + 100)
        await page.mouse.down()
        await page.mouse.move(viewport["x"] + 500, viewport["y"] + 350, steps=5)
        await page.mouse.up()
        await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "active")
        drawn = regions(actions)[-1]["points"]
        corners = (
            [(viewport["x"] + px - moved["x"]) / moved["width"] for px in (100, 500)],
            [(viewport["y"] + py - moved["y"]) / moved["height"] for py in (100, 350)],
        )
        assert [drawn[0][0], drawn[2][0]] == pytest.approx(corners[0], abs=0.004)
        assert [drawn[0][1], drawn[2][1]] == pytest.approx(corners[1], abs=0.004)
        drawn_box = pytest.approx([*drawn[0], *drawn[2]], abs=0.004)
        assert await outline(page) == drawn_box
        # The drag drew rather than panned, and the view then framed the new area on its centre.
        framed = framing(400 / moved["width"], 250 / moved["height"])
        assert framed not in ("1×", "2×")
        await expect(page.locator(".zoom-level")).to_have_text(framed)
        left, top, right, bottom = await in_view(page)
        assert (left + right) / 2 == pytest.approx(0.5, abs=0.01)
        assert (top + bottom) / 2 == pytest.approx(0.5, abs=0.01)
        assert 0.7 < bottom - top <= 0.81

        # A double-click resets the view; while a tool is armed it must not.
        await page.get_by_role("button", name="Draw a box").click()
        await page.mouse.dblclick(viewport["x"] + 300, viewport["y"] + 300)
        await expect(page.locator(".zoom-level")).to_have_text(framed)
        await page.keyboard.press("Escape")

        # Zoom's own area selection and the priority area tool never share a drag.
        await page.get_by_role("button", name="Zoom controls").click()
        await page.get_by_role("button", name="Select area").click()
        await expect(page.locator(".view-viewport")).to_have_attribute("data-selecting", "true")
        await page.get_by_role("button", name="Draw freehand").click()
        await expect(page.locator(".view-viewport")).to_have_attribute("data-selecting", "false")
        await expect(page.locator(".region-instruction")).to_be_visible()
        await expect(page.locator(".zoom-instruction:not(.region-instruction)")).to_be_hidden()
        await page.get_by_role("button", name="Zoom controls").click()
        await page.get_by_role("button", name="Select area").click()
        await expect(page.get_by_role("button", name="Draw freehand")).to_have_attribute(
            "aria-pressed", "false"
        )
        await expect(page.locator(".region-instruction")).to_be_hidden()
        await page.keyboard.press("Escape")
        await page.get_by_role("button", name="Zoom controls").click()
        await page.get_by_role("button", name="Reset", exact=True).click()
        await page.keyboard.press("Escape")
        await expect(page.locator(".zoom-level")).to_have_text("1×")

        # Window sizes, including a phone-width tile and an enlarged tile.
        for width, height in ((1024, 768), (390, 844), (1920, 1080)):
            await page.set_viewport_size({"width": width, "height": height})
            await settled(page)
            assert await outline(page) == drawn_box
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            # The one bar, with Clear showing, stays within the picture's surface.
            bar = await page.locator(".view-zoom").bounding_box()
            surface = await page.locator(".view-surface").bounding_box()
            assert surface["x"] <= bar["x"]
            assert bar["x"] + bar["width"] <= surface["x"] + surface["width"]
            assert bar["y"] + bar["height"] <= surface["y"] + surface["height"]
            await expect(page.get_by_role("button", name="Clear priority area")).to_be_visible()
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.get_by_role("button", name="Enlarge", exact=True).click()
        await settled(page)
        assert await outline(page) == drawn_box

        # Side by side with depth: the outline and new drawings belong to the colour half.
        await page.get_by_label("Depth display").select_option("side")
        await expect(page.locator(".depth-stage")).to_have_attribute("data-depth", "side")
        await settled(page)
        assert await outline(page) == drawn_box
        stage = await page.locator(".depth-stage").bounding_box()
        frame = await picture(page)
        assert frame["width"] == pytest.approx(stage["width"] / 2, abs=1)
        await page.get_by_role("button", name="Draw a box").click()
        # The stroke runs past the colour picture into the depth half and is clipped to it.
        await page.mouse.move(frame["x"] + frame["width"] * 0.5, frame["y"] + frame["height"] * 0.2)
        await page.mouse.down()
        await page.mouse.move(
            frame["x"] + frame["width"] * 1.5, frame["y"] + frame["height"] * 0.8, steps=6
        )
        await page.mouse.up()
        await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "active")
        clipped = regions(actions)[-1]["points"]
        assert [*clipped[0], *clipped[2]] == pytest.approx([0.5, 0.2, 1.0, 0.8], abs=0.004)
        assert await outline(page) == pytest.approx([0.5, 0.2, 1.0, 0.8], abs=0.004)
        # Beside depth the picture is half the view: the area is framed by its size there.
        await expect(page.locator(".zoom-level")).to_have_text(framing(0.25, 0.6))
        left, top, right, bottom = await in_view(page)
        assert 0 <= left < right <= 1 and (top + bottom) / 2 == pytest.approx(0.5, abs=0.01)
        assert bottom - top == pytest.approx(0.6 * 1.3, abs=0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("pointer", ["touch", "pen"])
async def test_touch_and_pen_draw_like_a_mouse(pointer):
    state = surgeon([camera()])
    async with dashboard(state) as (page, actions, _):
        await page.get_by_role("button", name="Draw freehand").click()
        assert await page.locator(".view-viewport").evaluate(
            "e => getComputedStyle(e).touchAction"
        ) == ("none")  # a finger draws rather than scrolling the page
        frame = await picture(page)
        path = [(0.2, 0.2), (0.5, 0.15), (0.8, 0.3), (0.75, 0.7), (0.4, 0.8), (0.2, 0.5)]
        await page.locator(".view-viewport").evaluate(
            """(viewport, [type, frame, path]) => {
                const fire = (name, [x, y]) => viewport.dispatchEvent(new PointerEvent(name, {
                    pointerId: 7, pointerType: type, isPrimary: true, button: 0, buttons: 1,
                    bubbles: true, cancelable: true,
                    clientX: frame.x + frame.width * x, clientY: frame.y + frame.height * y,
                }));
                fire('pointerdown', path[0]);
                for (const point of path.slice(1)) fire('pointermove', point);
                fire('pointerup', path[path.length - 1]);
            }""",
            [pointer, frame, path],
        )
        await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "active")
        sent = regions(actions)
        assert len(sent) == 1
        for point, expected in zip(sent[0]["points"], path, strict=True):
            assert point == pytest.approx(expected, abs=0.004)


@pytest.mark.asyncio
async def test_holoviz_card_lends_a_still_picture_to_draw_on():
    # H.265 is only ever shown in Holoviz, so its card is the one place to draw.
    native = camera(id="room:wide", name="Room camera", codec="h265")
    state = surgeon([native], native=["room:wide"])
    async with dashboard(state) as (page, actions, _):
        card = page.locator(".native-tile")
        tools = card.get_by_role("group", name="Room camera priority area")
        box = tools.get_by_role("button", name="Draw a box")
        lasso = tools.get_by_role("button", name="Draw freehand")
        clear = tools.get_by_role("button", name="Clear priority area")
        still = card.locator(".region-still")
        level = card.locator(".zoom-level")
        await expect(tools).to_be_visible()
        await expect(box).to_be_enabled()
        await expect(clear).to_be_hidden()
        # One row of controls on the card: the tools lead its zoom bar.
        assert await card.locator(".view-zoom").count() == 1
        assert await card.locator(".view-zoom > .view-region").count() == 1
        bar = card.get_by_role("group", name="Room camera view tools")
        assert await bar.get_by_role("button").all_inner_texts() == [
            "Draw a box",
            "Draw freehand",
            "Zoom out",
            "1×",
            "Zoom in",
        ]
        idle = [await box.bounding_box(), await lasso.bounding_box()]
        # No picture is requested from Holoviz until a drawing tool asks for one.
        await expect(still).to_be_hidden()
        await settled(page)
        assert stills(actions) == 0

        await box.click()
        await expect(still).to_be_visible()
        await expect(card.locator(STILL)).to_have_attribute("data-ready", "true")
        await expect(card.locator(".region-instruction")).to_have_text(
            "Drag a box around the area · Esc to cancel"
        )
        assert await still.evaluate("e => getComputedStyle(e).cursor") == "crosshair"
        # The still keeps the camera's shape and is not enlarged past what Holoviz lends.
        frame = await picture(page, STILL)
        assert frame["width"] / frame["height"] == pytest.approx(16 / 9, rel=0.01)
        assert frame["width"] <= 640
        await drag(page, (0.3, 0.25), (0.7, 0.75), target=STILL)
        await expect(card.locator(".region-overlay")).to_have_attribute("data-state", "active")
        sent = regions(actions)
        assert len(sent) == 1 and sent[0]["id"] == "room:wide"
        for point, expected in zip(sent[0]["points"], BOX, strict=True):
            assert point == pytest.approx(expected, abs=0.006)
        assert await outline(page, STILL) == pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.006)
        await expect(box).to_have_attribute("aria-pressed", "false")
        await expect(card.locator(".region-status")).to_have_text(
            "Priority area set by Dr. Rivera: picture detail is concentrated inside the outline."
        )
        # The Holoviz window is zoomed onto the new area; the still keeps showing the whole picture.
        await expect(level).to_have_text(framing(0.4, 0.5))
        # The card's bar grows to the right, so there Clear follows the drawing tools.
        assert (await bar.get_by_role("button").all_inner_texts())[:3] == [
            "Draw a box",
            "Draw freehand",
            "Clear priority area",
        ]
        assert [await box.bounding_box(), await lasso.bounding_box()] == idle
        await eventually(page, lambda: len(zooms(actions)) == 1)
        assert zooms(actions)[0] == pytest.approx(
            {"camera": "room:wide", "scale": 1.6, "x": 0.5, "y": 0.5}, abs=0.006
        )
        assert await outline(page, STILL) == pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.006)
        # The card is rebuilt when the window's state changes. The tools move to its new bar,
        # and the open picture, the area and the framed view carry over.
        await card.locator(".view-zoom").evaluate("bar => { bar.dataset.replaced = 'true'; }")
        state["native_views"]["room:wide"]["status"] = "starting"
        await expect(card.locator(".view-zoom:not([data-replaced])")).to_be_visible()
        assert await card.locator(".view-zoom").count() == 1
        assert await card.locator(".view-zoom > .view-region").count() == 1
        await expect(box).to_be_enabled()
        await expect(clear).to_be_enabled()
        await expect(level).to_have_text(framing(0.4, 0.5))
        await expect(still).to_be_visible()
        # The picture keeps refreshing while it is open.
        before = stills(actions)
        await page.wait_for_timeout(900)
        assert stills(actions) >= before + 2

        # Freehand, then Esc on an armed tool: the picture stays, nothing is sent.
        await lasso.click()
        centre = (frame["x"] + frame["width"] * 0.5, frame["y"] + frame["height"] * 0.5)
        radius = frame["height"] * 0.35
        await page.mouse.move(centre[0] + radius, centre[1])
        await page.mouse.down()
        for step in range(1, 91):
            angle = math.radians(step * 4)
            await page.mouse.move(
                centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)
            )
        await page.mouse.up()
        await expect(card.locator(".region-overlay")).to_have_attribute("data-state", "active")
        assert len(regions(actions)) == 2 and 8 <= len(regions(actions)[1]["points"]) <= 64
        await box.click()
        await page.keyboard.press("Escape")
        await expect(box).to_have_attribute("aria-pressed", "false")
        await expect(box).to_be_focused()
        await expect(still).to_be_visible()
        assert len(regions(actions)) == 2

        # Hiding the picture stops the requests and puts an armed tool down, so the next
        # status refresh does not open it again. Clear needs no picture.
        await lasso.click()
        await expect(lasso).to_have_attribute("aria-pressed", "true")
        await card.get_by_role("button", name="Hide picture", exact=True).click()
        await expect(still).to_be_hidden()
        await expect(lasso).to_have_attribute("aria-pressed", "false")
        await page.wait_for_timeout(500)
        quiet = stills(actions)
        await page.wait_for_timeout(1200)
        assert stills(actions) == quiet
        await expect(still).to_be_hidden()
        await clear.click()
        await expect(card.locator(".region-status")).to_be_hidden()
        assert regions(actions)[2] == {"id": "room:wide", "points": None}
        await expect(still).to_be_hidden()
        # The Holoviz window returns to the view it had before the first area.
        await expect(level).to_have_text("1×")
        await eventually(page, lambda: zooms(actions)[-1]["scale"] == 1)
        await expect(clear).to_be_hidden()

        # Leaving Holoviz removes the card and ends the requests.
        await lasso.click()
        await expect(still).to_be_visible()
        state["native_views"] = {}
        state["selected"] = []
        await expect(page.locator(".native-tile")).to_have_count(0)
        await page.wait_for_timeout(500)
        quiet = stills(actions)
        await page.wait_for_timeout(1200)
        assert stills(actions) == quiet


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(1440, 900), (390, 844)])
async def test_holoviz_card_follows_the_same_rules_as_a_browser_view(size):
    area = {"region": BOX, "region_by": "Dr. Rivera"}
    native = camera(id="room:wide", name="Room camera", codec="h265", **area)
    # View-only: the state is shown, nothing can be changed and no picture is fetched.
    state = surgeon([native], robot=False, native=["room:wide"])
    async with dashboard(state, size=size) as (page, actions, _):
        card = page.locator(".native-tile")
        tools = card.get_by_role("group", name="Room camera priority area")
        await expect(card.locator(".region-status")).to_have_text(
            "Priority area set by Dr. Rivera: picture detail is concentrated inside the outline."
        )
        for name in ("Draw a box", "Draw freehand", "Clear priority area"):
            await expect(tools.get_by_role("button", name=name)).to_be_disabled()
        await expect(tools.get_by_role("button", name="Draw a box")).to_have_attribute(
            "title", "View-only access cannot change the priority area"
        )
        await expect(card.locator(".region-still")).to_be_hidden()
        assert stills(actions) == 0 and regions(actions) == []
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # Settings that prevent an area: disabled with the reason.
    blocked = camera(
        id="room:wide",
        name="Room camera",
        codec="h265",
        region_unavailable="turn off adaptive quantization (aq, temporalaq) in the stream's "
        "advanced settings",
    )
    async with dashboard(surgeon([blocked], native=["room:wide"]), size=size) as (page, *_):
        card = page.locator(".native-tile")
        await expect(card.get_by_role("button", name="Draw a box")).to_be_disabled()
        await expect(card.locator(".region-status")).to_contain_text(
            "Priority area unavailable: turn off adaptive quantization"
        )
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # An encoder without support: the card is as it was before priority areas existed.
    plain = camera(id="room:wide", name="Room camera", codec="h265", region_supported=False)
    async with dashboard(surgeon([plain], native=["room:wide"]), size=size) as (page, actions, _):
        card = page.locator(".native-tile")
        await expect(card.locator(".region-native")).to_be_hidden()
        assert await card.get_by_role("button", name="Draw a box").count() == 0
        assert stills(actions) == 0
    # A controlling surgeon on a narrow screen draws within the card.
    async with dashboard(surgeon([native], native=["room:wide"]), size=size) as (page, actions, _):
        card = page.locator(".native-tile")
        await card.get_by_role("button", name="Draw a box").click()
        await expect(card.locator(STILL)).to_have_attribute("data-ready", "true")
        assert await outline(page, STILL) == pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.006)
        frame, tile = await picture(page, STILL), await card.bounding_box()
        assert frame["x"] >= tile["x"] and frame["x"] + frame["width"] <= tile["x"] + tile["width"]
        await drag(page, (0.1, 0.1), (0.5, 0.6), target=STILL)
        await expect(card.locator(".region-overlay")).to_have_attribute("data-state", "active")
        assert len(regions(actions)) == 1
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.asyncio
async def test_patient_preview_shows_and_changes_the_area():
    shown = camera(id="room:scope", region=BOX, region_by="Dr. Rivera")
    native = camera(id="room:wide", name="Room camera", region=BOX, region_by="Dr. Rivera")
    state = surgeon([shown, native], native=["room:wide"])
    async with dashboard(state) as (page, actions, _):
        card = page.locator(".native-tile")
        await card.get_by_role("button", name="Clear priority area").click()
        await expect(card.locator(".region-status")).to_be_hidden()
        assert regions(actions) == [{"id": "room:wide", "points": None}]
        # The camera still shown in the browser keeps its own area.
        assert await outline(page) == pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.004)

    # The patient dashboard is the room's own authority: its preview has working tools.
    patient = {
        "role": "patient",
        "sdk": "5.0",
        "endpoint_port": 7447,
        "nodes": [{"id": "room", "name": "Operating room", "status": "online"}],
        "cameras": [camera(region=BOX, region_by="Dr. Rivera")],
        "robots": [],
        "surgeons": [],
        "native_views": {},
    }
    async with dashboard(patient, ready="#equipment-rows tr") as (page, actions, _):
        await (
            page.locator("#equipment-rows")
            .get_by_role("button", name="Preview", exact=True)
            .first.click()
        )
        await expect(page.locator(".video-tile")).to_have_count(1)
        assert await outline(page) == pytest.approx([0.3, 0.25, 0.7, 0.75], abs=0.004)
        await page.get_by_role("button", name="Clear priority area").click()
        await expect(page.locator(".region-overlay")).to_be_hidden()
        assert regions(actions) == [{"id": "room:scope", "points": None}]
        await page.get_by_role("button", name="Draw a box").click()
        await drag(page, (0.1, 0.1), (0.5, 0.6))
        await expect(page.locator(".region-overlay")).to_have_attribute("data-state", "active")
        assert len(regions(actions)) == 2


@pytest.mark.asyncio
async def test_stream_settings_explain_the_conflict_with_adaptive_quantization():
    refusal = "Clear the priority area before turning on adaptive quantization (aq, temporalaq)"

    def patient(**changes):
        return {
            "role": "patient",
            "sdk": "5.0",
            "endpoint_port": 7447,
            "nodes": [{"id": "room", "name": "Operating room", "status": "online"}],
            "cameras": [camera(codecs=["h264", "h265", "nvjpeg"], **changes)],
            "robots": [],
            "surgeons": [],
            "native_views": {},
        }

    async def advanced(page):
        await page.get_by_role("button", name="Stream settings", exact=True).click()
        await expect(page.get_by_role("dialog", name="Change encoding")).to_be_visible()
        await page.get_by_text("Encoder settings", exact=True).click()
        await page.get_by_text("Advanced", exact=True).click()

    state = patient(region=BOX, region_by="Dr. Rivera")
    async with dashboard(state, refuse={"camera.start": refusal}, ready="#equipment-rows tr") as (
        page,
        actions,
        _,
    ):
        await advanced(page)
        note = page.locator("#stream-region-note")
        await expect(note).to_be_visible()
        await expect(note).to_contain_text("cannot be combined with a priority area")
        await page.locator("#stream-extra").fill("aq=8")
        await page.get_by_role("button", name="Apply encoding", exact=True).click()
        # The node's refusal stays in the form, beside the setting that caused it.
        await expect(page.locator("#stream-error")).to_have_text(refusal)
        await expect(page.get_by_role("dialog", name="Change encoding")).to_be_visible()
        sent = [a for a in actions if a["action"] == "camera.start"]
        assert sent[0]["params"]["settings"]["encoder_extra"] == "aq=8"
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # A node whose encoder cannot use an area shows the form as before.
    async with dashboard(patient(region_supported=False), ready="#equipment-rows tr") as (page, *_):
        await advanced(page)
        await expect(page.locator("#stream-extra")).to_be_visible()
        await expect(page.locator("#stream-region-note")).to_be_hidden()
