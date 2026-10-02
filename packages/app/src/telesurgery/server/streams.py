# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Viewer connections go straight to the selected patient-side node."""

import asyncio
import logging

from telesurgery_core.diagnostics.trace import arrive
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.tls import client_context, pin_peer

LOG = logging.getLogger(__name__)


class DirectStreams:
    def __init__(self, app):
        self.app = app
        self.tasks, self.errors = {}, {}
        self.lock = asyncio.Lock()

    async def select(self, cameras):
        async with self.lock:
            for camera in self.tasks.keys() - cameras:
                task = self.tasks.pop(camera)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self.errors.pop(camera, None)
            for camera in cameras - self.tasks.keys():
                self.tasks[camera] = asyncio.create_task(self._run(camera))

    async def _run(self, camera):
        async def reject(peer, method, params):
            raise PermissionError("Video connections do not accept commands")

        async def event(peer, name, params, payload):
            if name != "video" or params.get("camera") != camera:
                raise ValueError("Unexpected video source")
            if self.app.role == "patient" or (
                self.app.remote_status.get("status") == "approved" and camera in self.app.selected
            ):
                timing = peer.delivery(
                    params.get("timing"), frame_bytes=params.get("transport_bytes")
                )
                timing["trace"] = arrive(params.get("trace"), timing)
                if self.app.role == "patient":
                    await self.app.media.put(camera, params["header"], payload, timing)
                else:
                    self.app.video.put(camera, params["header"], payload, timing)

        while True:
            peer = writer = None
            try:
                route = (
                    await self.app._viewer_route(camera)
                    if self.app.role == "patient"
                    else await self.app.remote.call("viewer.ticket", {"camera": camera})
                )
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(route["host"], route["port"], ssl=client_context()), 5
                )
                pin_peer(
                    writer,
                    f"{route['host']}:{route['port']}",
                    self.app.directory / "video-peers",
                    route["fingerprint"],
                )
                peer = Peer(reader, writer, reject, event, clock=self.app.clock).start()
                await peer.call("viewer.attach", {"ticket": route["ticket"]})
                self.errors.pop(camera, None)
                await peer.closed.wait()
            except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
                message = f"Direct video connection failed: {exc}"
                if self.errors.get(camera) != message:
                    LOG.warning("%s: %s", camera, message)
                self.errors[camera] = message
            finally:
                if peer:
                    await peer.close()
                elif writer:
                    writer.close()
            await asyncio.sleep(2)

    async def close(self):
        await self.select(set())
