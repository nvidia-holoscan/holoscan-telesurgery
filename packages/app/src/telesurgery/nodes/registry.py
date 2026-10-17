# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persist and manage explicitly enrolled device nodes."""

import asyncio
import contextlib
import hashlib
import re
import secrets

from telesurgery_core.configuration import load, save


class NodeRegistry:
    def __init__(self, app):
        self.app = app
        self.path = app.directory / "nodes.yaml"
        self.configs = load(self.path)
        self.pending = {}
        self.lock = asyncio.Lock()

    def start(self):
        for key, config in self.configs.items():
            self.app.nodes[key] = {
                "name": config["name"],
                "status": "offline",
            }

    def request(self, peer, params):
        token, name = params.get("token"), params.get("name")
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("Invalid node credential")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Node name must be between 1 and 80 characters")
        if params.get("environment") not in {None, "mira", "franka", "versius"}:
            raise ValueError("Unknown node environment")
        devices = params.get("devices", [])
        if (
            not isinstance(devices, list)
            or len(devices) > 32
            or any(
                not isinstance(device, dict)
                or set(device) != {"name", "kind", "powers_motors"}
                or any(
                    not isinstance(device.get(field), str) or not 1 <= len(device[field]) <= 80
                    for field in ("name", "kind")
                )
                or type(device.get("powers_motors")) is not bool
                for device in devices
            )
        ):
            raise ValueError("Invalid node device summary")
        key = next(
            (
                key
                for key, node in self.configs.items()
                if secrets.compare_digest(node.get("token", ""), token)
            ),
            hashlib.sha256(token.encode()).hexdigest()[:12],
        )
        if key in self.app.peer_nodes.values():
            raise PermissionError("This node is already connected")
        known = self.configs.get(key)
        if known:
            if not secrets.compare_digest(known.get("token", ""), token):
                raise PermissionError("Node identity does not match its approval")
            if known.get("devices", []) == devices:
                return {"id": key, "status": "approved"}
        if any(item["peer"] == peer.id and other != key for other, item in self.pending.items()):
            raise PermissionError("A connection can request access for only one node")
        existing = self.pending.get(key)
        if existing and existing["peer"] != peer.id:
            raise PermissionError("This node already has an active request")
        if existing and existing.get("devices", []) != devices:
            raise PermissionError("Device summary changed; reconnect to request approval")
        if not existing:
            if len(self.pending) >= 32:
                raise RuntimeError("Too many pending node requests")
            self.pending[key] = {
                "peer": peer.id,
                "name": name.strip(),
                "ip": peer.writer.get_extra_info("peername")[0],
                "environment": params.get("environment"),
                "devices": devices,
                "token": token,
                "status": "pending",
            }
        return {"id": key, "status": self.pending[key]["status"]}

    def requests(self):
        return [
            {
                "id": key,
                **{field: item[field] for field in ("name", "ip", "environment")},
                "devices": item.get("devices", []),
            }
            for key, item in self.pending.items()
            if item["status"] == "pending"
        ]

    async def decide(self, key, approve, *, confirm_physical=False):
        async with self.lock:
            request = self.pending.get(key)
            if not request or request["status"] != "pending":
                raise ValueError("This node request is no longer pending")
            if approve:
                if request.get("devices") and confirm_physical is not True:
                    raise PermissionError(
                        "Confirm physical device startup before approving this node"
                    )
                config = {field: request[field] for field in ("name", "ip", "token")}
                config["devices"] = request.get("devices", [])
                save(self.path, {**self.configs, key: config})
                self.configs[key] = config
                self.app.nodes[key] = {"name": request["name"], "status": "starting"}
            request["status"] = "approved" if approve else "rejected"
        return True

    def disconnected(self, peer):
        self.pending = {key: item for key, item in self.pending.items() if item["peer"] != peer}

    async def remove(self, key):
        async with self.lock, self.app.control_lock:
            if key not in self.configs:
                raise ValueError("Unknown node")
            for robot in [name for name in self.app.owners if name.startswith(f"{key}:")]:
                await self.app._release(robot)
                for records in (
                    self.app.owners,
                    self.app.robot_state,
                    self.app.robot_timings,
                    self.app.faults,
                ):
                    records.pop(robot, None)
            with contextlib.suppress(ConnectionError, RuntimeError, TimeoutError):
                await self.app.node_call(key, "node.remove")
            remaining = {name: value for name, value in self.configs.items() if name != key}
            save(self.path, remaining)
            self.configs = remaining  # Reject reconnects before closing the current connection.
            for peer_id, node in list(self.app.peer_nodes.items()):
                if node == key:
                    self.app.peer_nodes.pop(peer_id)
                    await self.app.peers.pop(peer_id)["peer"].close()
            node = self.app.nodes.pop(key, {})
            cameras = {camera for camera in self.app.media.feeds if camera.startswith(f"{key}:")}
            cameras.update(f"{key}:{camera['id']}" for camera in node.get("cameras", []))
            cameras.update(
                camera for camera in self.app.native.windows if camera.startswith(f"{key}:")
            )
            for item in self.app.peers.values():
                item["selected"].difference_update(cameras)
                item["peer"].clear_frames()
            for camera in cameras:
                await self.app.native.close(camera)
                await self.app.media.clear(camera)
            return True
