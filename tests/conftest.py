# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise node admission over real TLS without launching device subprocesses."""

import asyncio
import secrets

import pytest_asyncio


@pytest_asyncio.fixture
async def enrolled_node():
    from telesurgery.nodes.client import NodeClient

    tasks = []

    async def start(patient, directory, *, name="room", environment=None, config=None):
        settings = config or {
            "host": "127.0.0.1",
            "port": patient.endpoint_port,
            "name": name,
            "token": secrets.token_urlsafe(32),
            "video_port": 0,
        }
        node = NodeClient(directory, settings, environment)
        task = asyncio.create_task(node.run())
        tasks.append(task)
        async with asyncio.timeout(20):
            while not node.ready:
                if task.done():
                    await task
                for request in patient.node_registry.requests():
                    if request["name"] == settings["name"]:
                        await patient.action("node.approve", {"id": request["id"]})
                await asyncio.sleep(0.02)
        key = next(key for key, value in patient.nodes.items() if value["name"] == settings["name"])
        return node, key

    yield start
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
