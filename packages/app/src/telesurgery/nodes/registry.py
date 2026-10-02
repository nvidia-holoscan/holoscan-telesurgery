# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persist and manage the patient's remote node connections."""

import asyncio
import hashlib
import re
import secrets
import socket
import ssl

from telesurgery.nodes.connection import ServiceConnection
from telesurgery.nodes.deploy import deploy
from telesurgery.nodes.pairing import credentials, endpoint
from telesurgery_core.configuration import load, save


class NodeRegistry:
    def __init__(self, app, addresses=()):
        self.app = app
        self.path = app.directory / "nodes.yaml"
        self.configs = load(self.path)
        self.links = {}
        self.lock = asyncio.Lock()
        if addresses:
            if app.role != "patient" or app.environment:
                raise ValueError("--nodes is for a patient in physical mode")
            for address in sorted({endpoint(value)[2] for value in addresses}):
                if not any(node.get("address") == address for node in self.configs.values()):
                    self.configs[secrets.token_hex(6)] = {"kind": "service", "address": address}
            save(self.path, self.configs)

    def start(self):
        for key, config in self.configs.items():
            self.app.nodes[key] = {
                "name": endpoint(config["address"])[0]
                if config.get("kind") == "service"
                else config.get("target", key),
                "status": "offline",
            }
            if config.get("kind") == "service":
                link = ServiceConnection(self.app, key, config)
                self.links[key] = self.app.task(link.run())

    async def connect(self, address, code):
        if self.app.environment:
            raise ValueError("Simulation uses its own single node")
        _, _, address = endpoint(address.strip() if isinstance(address, str) else address)
        identity, token = credentials(code)
        async with self.lock:
            existing = next(
                (
                    key
                    for key, node in self.configs.items()
                    if node.get("kind") == "service"
                    and (node.get("fingerprint") == identity or node["address"] == address)
                ),
                None,
            )
            if existing and self.app.nodes.get(existing, {}).get("status") == "online":
                raise ValueError("This node is already connected")
            key = existing or secrets.token_hex(6)
            config = {
                "kind": "service",
                "address": address,
                "fingerprint": identity,
                "token": token,
            }
            if existing:
                self.links[key].cancel()
                await asyncio.gather(self.links[key], return_exceptions=True)
            link = ServiceConnection(self.app, key, config)
            try:
                await link.connect()
                save(self.path, {**self.configs, key: config})
                self.configs[key] = config
            except BaseException:
                await link.disconnect()
                if existing:
                    previous = ServiceConnection(self.app, key, self.configs[key])
                    self.links[key] = self.app.task(previous.run())
                else:
                    self.app.nodes.pop(key, None)
                    self.configs.pop(key, None)
                raise
            self.links[key] = self.app.task(link.run())
            return {"id": key}

    async def add(self, target, sdk, environment=None):
        if self.app.environment:
            raise ValueError("Add SSH nodes in physical mode")
        if (
            not isinstance(target, str)
            or not re.fullmatch(r"[A-Za-z0-9_.@:-]+", target)
            or target.startswith("-")
        ):
            raise ValueError("Use an SSH hostname, alias, or user@host")
        if sdk not in {4, 5}:
            raise ValueError("Choose SDK 4 or SDK 5")
        if environment not in {None, "mira", "franka"}:
            raise ValueError("Choose physical devices, MIRA or Franka")
        # Resolve the SSH alias without exposing the user's SSH configuration in the UI.
        process = await asyncio.create_subprocess_exec(
            "ssh", "-G", target, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        output, _ = await process.communicate()
        host = next(
            (
                line.split()[1]
                for line in output.decode().splitlines()
                if line.startswith("hostname ")
            ),
            target,
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect((host, 22))
            address = probe.getsockname()[0]
        existing = next(
            (key for key, node in self.configs.items() if node.get("target") == target), None
        )
        if existing and self.app.nodes.get(existing, {}).get("status") in {"online", "deploying"}:
            raise ValueError("This node is already connected or deploying")
        node_id = existing or secrets.token_hex(6)
        cert = ssl.PEM_cert_to_DER_cert((self.app.directory / "endpoint.pem").read_text())
        config = {
            "id": node_id,
            "token": secrets.token_urlsafe(32),
            "host": address,
            "port": self.app.endpoint_port,
            "fingerprint": hashlib.sha256(cert).hexdigest(),
            "environment": environment,
        }
        self.configs[node_id] = {**config, "target": target, "sdk": sdk}
        save(self.path, self.configs)
        self.app.nodes[node_id] = {"name": target, "status": "deploying", "sdk": str(sdk)}

        async def install():
            try:
                await deploy(target, config, sdk, self.app.directory / f"deploy-{node_id}.log")
            except Exception as exc:
                self.app.nodes[node_id].update(status="error", error=str(exc))

        self.links[node_id] = self.app.task(install())
        return {"id": node_id}

    async def remove(self, key):
        if key == "host":
            raise ValueError("The local host cannot be removed")
        async with self.lock, self.app.control_lock:
            if key not in self.configs:
                raise ValueError("Unknown node")
            remaining = {name: value for name, value in self.configs.items() if name != key}
            save(self.path, remaining)
            self.configs = remaining  # Reject reconnects before closing the current connection.
            for robot in [name for name in self.app.owners if name.startswith(f"{key}:")]:
                await self.app._release(robot)
                for records in (
                    self.app.owners,
                    self.app.robot_state,
                    self.app.robot_timings,
                    self.app.faults,
                ):
                    records.pop(robot, None)
            task = self.links.pop(key, None)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
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
            viewers = [*self.app.viewer_peers.values(), *self.app.viewer_tickets.values()]
            cameras.update(
                item["camera"] for item in viewers if item["camera"].startswith(f"{key}:")
            )
            for owner in {item["owner"] for item in viewers if item["camera"] in cameras}:
                await self.app._close_viewers(owner, cameras)
            for item in self.app.peers.values():
                item["selected"].difference_update(cameras)
                item["peer"].clear_frames()
            for camera in cameras:
                await self.app.native.close(camera)
                await self.app.media.clear(camera)
            return True
