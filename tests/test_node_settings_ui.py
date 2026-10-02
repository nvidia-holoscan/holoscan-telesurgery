# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Both enrollment paths remain usable, including errors and small screens."""

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright, expect


@pytest.mark.asyncio
async def test_add_running_node_and_ssh(tmp_path):
    static = Path(__file__).parents[1] / "packages/app/src/telesurgery/server/static"
    actions = []
    state = {
        "role": "patient",
        "sdk": "5",
        "nodes": [
            {
                "id": "spark",
                "name": "Spark",
                "address": "spark:7448",
                "connection": "service",
                "status": "unpaired",
                "paired": False,
            }
        ],
        "cameras": [],
        "robots": [],
        "surgeons": [],
    }

    async def route(request):
        path = request.request.url.removeprefix("http://localhost:8777/")
        if path == "api/status":
            await request.fulfill(json=state)
        elif path == "api/action":
            body = json.loads(request.request.post_data)
            actions.append(body)
            if body["action"] == "node.remove":
                state["nodes"] = [{"id": "host", "name": "Host", "status": "online"}]
            elif body["action"] == "node.environment":
                state["nodes"][0].update(
                    environment=body["params"]["environment"],
                    simulation={"status": "loading", "stage": "Loading environment assets"},
                )
            await request.fulfill(
                status=409 if len(actions) == 1 else 200,
                json={"error": "Incorrect pairing code"}
                if len(actions) == 1
                else {"result": {"id": "node"}},
            )
        else:
            await request.fulfill(path=static / (path.removeprefix("static/") or "index.html"))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 960})
            await page.route("http://localhost:8777/**", route)
            await page.goto("http://localhost:8777/#nodes")
            await expect(
                page.locator("#node-identity").get_by_text("Needs pairing", exact=True)
            ).to_be_visible()
            await (
                page.locator("#node-identity")
                .get_by_role("button", name="Pair node", exact=True)
                .click()
            )
            await expect(page.get_by_label("Node address", exact=True)).to_have_value("spark:7448")
            await page.get_by_label("Node address", exact=True).fill("10.111.19.209:7448")
            await page.get_by_label("Pairing code", exact=True).fill("example-pairing-code")
            await page.screenshot(path=str(tmp_path / "connect-node.png"))
            await page.get_by_role("button", name="Connect node", exact=True).click()
            await expect(page.get_by_role("alert")).to_have_text("Incorrect pairing code")
            await expect(page.get_by_role("dialog", name="Add a patient node")).to_be_visible()
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.screenshot(path=str(tmp_path / "connect-node-mobile.png"))
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.get_by_role("button", name="Connect node", exact=True).click()
            await expect(page.locator("#node-dialog")).not_to_be_visible()
            assert actions[-1] == {
                "action": "node.connect",
                "params": {"address": "10.111.19.209:7448", "code": "example-pairing-code"},
            }
            await page.get_by_role("button", name="Add node", exact=True).click()
            await expect(page.get_by_label("Pairing code", exact=True)).to_have_value("")
            await page.get_by_label("Connection", exact=True).select_option("ssh")
            await page.get_by_label("SSH host", exact=True).fill("user@thor")
            await page.get_by_label("Holoscan SDK", exact=True).select_option("4")
            await (
                page.locator("#node-form")
                .get_by_label("Environment", exact=True)
                .select_option("franka")
            )
            await page.screenshot(path=str(tmp_path / "deploy-node-mobile.png"))
            await page.get_by_role("button", name="Deploy node", exact=True).click()
            await expect(page.locator("#node-dialog")).not_to_be_visible()
            assert actions[-1] == {
                "action": "node.add",
                "params": {"target": "user@thor", "sdk": 4, "environment": "franka"},
            }
            state["nodes"][0].update(status="online", paired=True)
            await expect(page.get_by_role("button", name="Environment", exact=True)).to_be_hidden()
            state["nodes"][0]["connection"] = "ssh"
            await page.get_by_role("button", name="Environment", exact=True).click()
            await (
                page.locator("#environment-form")
                .get_by_label("Environment", exact=True)
                .select_option("mira")
            )
            await page.screenshot(path=str(tmp_path / "node-environment-mobile.png"))
            await page.get_by_role("button", name="Apply", exact=True).click()
            await expect(page.locator("#environment-dialog")).to_be_hidden()
            assert actions[-1] == {
                "action": "node.environment",
                "params": {"id": "spark", "environment": "mira"},
            }
            await expect(page.locator("#simulation-progress")).to_contain_text(
                "Loading environment assets"
            )
            await expect(
                page.get_by_role("button", name="Simulation logs", exact=True)
            ).to_be_visible()
            await page.get_by_role("button", name="Remove Spark", exact=True).click()
            await page.get_by_role("button", name="Cancel", exact=True).click()
            assert actions[-1]["action"] == "node.environment"
            await page.get_by_role("button", name="Remove Spark", exact=True).click()
            await page.screenshot(path=str(tmp_path / "remove-node-mobile.png"))
            await page.get_by_role("button", name="Remove node", exact=True).click()
            await expect(page.locator("#remove-node-dialog")).to_be_hidden()
            await expect(page.locator("#node-name")).to_have_text("Host · Host")
            assert actions[-1] == {"action": "node.remove", "params": {"id": "spark"}}
            await expect(page.locator(".node-remove:visible")).to_have_count(0)
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_node_grid_alignment_at_different_counts_and_widths(tmp_path):
    static = Path(__file__).parents[1] / "packages/app/src/telesurgery/server/static"
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
                        await expect(page.locator("#node-name")).to_have_text("Host · Host")
                        continue
                    boxes = await page.locator("#nodes .device").evaluate_all("""
                    cards => cards.map(card => {
                        const box=card.getBoundingClientRect();
                        const link=card.querySelector('.node-open').getBoundingClientRect();
                        return {width:box.width,height:box.height,footer:link.y-box.y};
                    })""")
                    assert len(boxes) == count
                    assert all(box["width"] <= 480 for box in boxes)
                    for key in ("width", "height", "footer"):
                        assert max(box[key] for box in boxes) - min(box[key] for box in boxes) < 1
                    if count in (2, 4, 9) and width != 1024:
                        await page.screenshot(
                            path=str(tmp_path / f"nodes-{count}-{width}.png"), full_page=True
                        )
        finally:
            await browser.close()
