# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Patient connection to a manually started node, including restart recovery."""

import asyncio
import time

from telesurgery.nodes.pairing import endpoint
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.tls import client_context, pin_peer


class ServiceConnection:
    def __init__(self, app, key, config):
        self.app, self.key, self.config = app, key, config
        self.peer = None
        self.last_log = None

    def log(self, message):
        if message == self.last_log:
            return
        self.last_log = message
        path = self.app.directory / f"connect-{self.key}.log"
        # Bounded connection history; no per-frame logging or credentials.
        lines = path.read_text().splitlines()[-99:] if path.exists() else []
        lines.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}")
        path.write_text("\n".join(lines) + "\n")

    async def connect(self):
        host, port, address = endpoint(self.config["address"])
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=client_context()), 5
            )
        except (OSError, TimeoutError) as exc:
            raise ConnectionError(
                f"Cannot connect to {address}. Check the node service and port."
            ) from exc
        try:
            if self.config.get("fingerprint"):
                pin_peer(
                    writer, address, self.app.directory / "node-peers", self.config["fingerprint"]
                )
        except Exception:
            writer.close()
            await writer.wait_closed()
            raise

        async def request(peer, method, params):
            if method == "node.time":
                return {"server_time": time.time()}
            raise PermissionError("Node connections only carry devices and video")

        self.peer = Peer(reader, writer, request, clock=self.app.clock).start()
        try:
            if not self.config.get("token"):
                info = await self.peer.call("node.info", timeout=5)
                self.app.nodes[self.key] = {
                    "name": info["name"],
                    "sdk": info["sdk"],
                    "status": "unpaired",
                }
                await self.peer.close()
                self.peer = None
                self.log(f"Service available at {address}; pairing required")
                return
            inventory = await self.peer.call("node.attach", {"token": self.config["token"]})
            self.app.peers[self.peer.id] = {"peer": self.peer, "selected": set()}
            self.app.peer_nodes[self.peer.id] = self.key
            self.app.nodes[self.key] = {**inventory, "status": "online"}
            for key, owner in self.app.owners.items():
                if key.startswith(f"{self.key}:"):
                    owner.release()
                    owner.ready = True
            self.log(f"Connected to {address}")
        except BaseException:
            await self.disconnect()
            raise

    async def disconnect(self):
        if self.peer:
            self.app.peer_nodes.pop(self.peer.id, None)
            self.app.peers.pop(self.peer.id, None)
            await self.peer.close()
            self.peer = None
        if self.key in self.app.nodes:
            self.app.nodes[self.key]["status"] = "offline"
        for key, owner in self.app.owners.items():
            if key.startswith(f"{self.key}:"):
                owner.release()
                owner.ready = False

    async def run(self):
        try:
            while True:
                try:
                    if self.peer is None:
                        await self.connect()
                    while self.peer:
                        inventory = await self.peer.call("inventory")
                        self.app.nodes[self.key] = {**inventory, "status": "online"}
                        await asyncio.sleep(2)
                except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                    await self.disconnect()
                    self.app.nodes[self.key]["error"] = (
                        "" if isinstance(exc, (ConnectionError, TimeoutError)) else str(exc)
                    )
                    self.log(str(exc))
                await asyncio.sleep(2)
        finally:
            await self.disconnect()
