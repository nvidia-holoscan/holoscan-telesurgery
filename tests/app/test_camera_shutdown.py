# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A cancelled node disconnect still joins its camera workers and closes sockets."""

import asyncio

import pytest
import zmq
from telesurgery.nodes import local


@pytest.mark.asyncio
async def test_cancelling_camera_stop_finishes_cleanup(tmp_path, monkeypatch):
    node = local.LocalNode(tmp_path, None)
    entered, finished = asyncio.Event(), asyncio.Event()

    async def terminate(process):
        entered.set()
        await finished.wait()

    monkeypatch.setattr(local, "_terminate", terminate)
    socket = node.context.socket(zmq.SUB)
    tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]
    node.workers["camera"] = {
        "process": object(),
        "socket": socket,
        "reader": tasks[0],
        "watcher": tasks[1],
    }
    stopping = asyncio.create_task(node.stop_camera("camera"))
    await entered.wait()
    stopping.cancel()
    await asyncio.sleep(0)
    assert not stopping.done()
    finished.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stopping, 1)
    assert socket.closed and all(task.done() for task in tasks)
    await asyncio.wait_for(node.close(), 1)
