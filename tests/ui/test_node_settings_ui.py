# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Node requests and equipment remain usable on desktop and small screens."""

from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
async def test_node_requests_approval_rejection_and_removal(tmp_path):
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    actions = []
    state = {
        "role": "patient",
        "sdk": "5",
        "nodes": [],
        "node_requests": [],
        "cameras": [],
        "robots": [],
        "surgeons": [],
    }

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        elif path == "api/action":
            body = request.request.post_data_json
            actions.append(body)
            key = body["params"]["id"]
            if body["action"] == "node.approve":
                item = next(x for x in state["node_requests"] if x["id"] == key)
                state["nodes"].append({**item, "status": "online"})
            if body["action"] == "node.remove":
                state["nodes"] = [x for x in state["nodes"] if x["id"] != key]
            state["node_requests"] = [x for x in state["node_requests"] if x["id"] != key]
            await request.fulfill(json={"result": True})
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/#nodes")
            await expect(page.locator("#node-start")).to_be_visible()
            await expect(page.get_by_role("button", name="Add node", exact=True)).to_have_count(0)
            state["node_requests"] = [
                {"id": name, "name": name, "ip": "192.168.1.2", "environment": env}
                for name, env in [("host-mira", "mira"), ("host-franka", "franka")]
            ]
            await expect(page.locator(".node-request")).to_have_count(2)
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await (
                page.locator(".node-request")
                .filter(has_text="host-mira")
                .get_by_role("button", name="Approve", exact=True)
                .click()
            )
            await (
                page.locator(".node-request")
                .filter(has_text="host-franka")
                .get_by_role("button", name="Reject", exact=True)
                .click()
            )
            await expect(page.locator("#node-name")).to_have_text("host-mira")
            await expect(page.locator("#node-requests-panel")).to_be_hidden()
            await (
                page.locator("#node-identity")
                .get_by_role("button", name="Remove host-mira", exact=True)
                .click()
            )
            await page.get_by_role("button", name="Remove node", exact=True).click()
            await expect(page.locator("#node-start")).to_be_visible()
            assert [x["action"] for x in actions] == ["node.approve", "node.reject", "node.remove"]
            assert not errors
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_node_grid_alignment_at_different_counts_and_widths(tmp_path):
    static = Path(__file__).parents[2] / "packages/app/src/telesurgery/server/static"
    state = {
        "role": "patient",
        "sdk": "5",
        "nodes": [],
        "cameras": [],
        "robots": [],
        "surgeons": [],
    }

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("http://localhost:8777/**", route)
            for count in (1, 2, 3, 4, 9, 16):
                state["nodes"] = [
                    {
                        "id": "host" if i == 0 else str(i),
                        "name": "Host" if i == 0 else f"Node {i} with a long descriptive room name",
                        "status": ["online", "offline", "unpaired", "error"][i % 4],
                        "connection": "service",
                        "paired": i % 4 != 2,
                        "error": "Long deployment error\n" * 100 if i % 4 == 3 else "",
                    }
                    for i in range(count)
                ]
                await page.goto("http://localhost:8777/#nodes")
                await expect(page.locator("#nav-node-count")).to_have_text(str(count))
                for width in (1600, 1024, 390):
                    await page.set_viewport_size({"width": width, "height": 1000})
                    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    if count == 1:
                        await expect(page.locator("#node-name")).to_have_text("Host")
                        continue
                    boxes = await page.locator("#nodes .device").evaluate_all("""
                    cards => cards.map(card => {
                        const box=card.getBoundingClientRect();
                        const title=card.querySelector('.node-card-identity');
                        const link=title.getBoundingClientRect();
                        return {width:box.width,height:box.height,header:link.y-box.y};
                    })""")
                    assert len(boxes) == count
                    assert all(box["width"] <= 480 for box in boxes)
                    for key in ("width", "height", "header"):
                        assert max(box[key] for box in boxes) - min(box[key] for box in boxes) < 1
                    if count in (2, 4, 9) and width != 1024:
                        await page.screenshot(
                            path=str(tmp_path / f"nodes-{count}-{width}.png"), full_page=True
                        )
        finally:
            await browser.close()
