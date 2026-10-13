# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise node admission over real TLS without launching device subprocesses."""

import asyncio
import os
import secrets
import select
import shutil
import subprocess

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def virtual_display(tmp_path_factory):
    """Native window tests must never map a window onto the developer's desktop."""
    executable = shutil.which("Xvfb")
    if not executable:
        pytest.skip("Native window tests require Xvfb; run setup.sh")
    directory = tmp_path_factory.mktemp("xvfb")
    read_fd, write_fd = os.pipe()
    try:
        with (directory / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    executable,
                    "-displayfd",
                    str(write_fd),
                    "-screen",
                    "0",
                    "1920x1080x24",
                    "-nolisten",
                    "tcp",
                ],
                pass_fds=(write_fd,),
                stdout=subprocess.DEVNULL,
                stderr=log,
            )
            os.close(write_fd)
            write_fd = None
            try:
                if not select.select([read_fd], [], [], 10)[0]:
                    pytest.fail("Xvfb did not become ready within 10 seconds")
                number = os.read(read_fd, 64).decode().strip()
                if not number.isdigit():
                    log.seek(0)
                    pytest.fail("Xvfb failed to start: " + log.read())
                yield f":{number}"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


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
