# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Patient and surgeon services; localhost UI, separate encrypted application endpoint."""

import asyncio
import contextlib
import hashlib
import logging
import math
import secrets
import ssl
import time
from pathlib import Path

from telesurgery.nodes.pairing import endpoint
from telesurgery.nodes.registry import NodeRegistry
from telesurgery.nodes.service import NodeService
from telesurgery.server.media import Media
from telesurgery.server.streams import DirectStreams
from telesurgery.server.viewers import NativeViews
from telesurgery_core.control.access import Access, Ownership
from telesurgery_core.diagnostics.benchmark import Samples
from telesurgery_core.diagnostics.clock import Clock
from telesurgery_core.diagnostics.trace import arrive, mark, source
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.transport.tls import client_context, pin_peer, server_context
from telesurgery_runtime.pipeline import Executor, VideoBridge
from telesurgery_runtime.sdk import require_sdk

LOG = logging.getLogger(__name__)


class Application:
    def __init__(
        self, role, directory, endpoint_port=7447, environment=None, *, sim_gui=False, nodes=()
    ):
        self.role, self.directory = role, Path(directory)
        self.endpoint_port, self.environment = endpoint_port, environment
        self.sim_gui = sim_gui
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.engine = Executor(role)
        self.media = Media(self._media_changed)
        self.access = Access(self.directory / "surgeons.yaml" if role == "patient" else None)
        self.native = NativeViews(self.directory / "viewers")
        self.viewer_tickets, self.viewer_peers = {}, {}
        self.peers, self.peer_nodes, self.nodes, self.owners = {}, {}, {}, {}
        self.tokens, self.sequences, self.selected = {}, {}, set()
        self.control_lock = asyncio.Lock()
        self.tasks = set()
        self.connections = set()
        self.local = self.server = self.remote = self.video = self.simulation = None
        self.remote_status = {"status": "disconnected"}
        self.robot_state, self.faults = {}, {}
        self.address = ""
        self.timings = {}
        self.robot_timings = {}
        self.clock = Clock()
        self.streams = DirectStreams(self)
        self.node_registry = NodeRegistry(self, nodes)

    def task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def run(self, function, *args, timeout=2):
        return await asyncio.wrap_future(self.engine.submit(function, *args, timeout=timeout))

    async def start(self):
        self.task(self.clock.watch())
        await asyncio.to_thread(self.engine.start)
        if self.role == "patient":
            manifest = None
            if self.environment:
                from telesurgery_sim.launch import Simulation

                self.simulation = Simulation(
                    self.environment, self.directory / "simulation", gui=self.sim_gui
                )
                manifest = await self.simulation.start()
            self.local = NodeService(self.directory / "host", self._local_video, manifest)
            await self.local.start()
            self.nodes["host"] = await self.local.call("inventory")
            self.nodes["host"].update(status="online", environment=self.environment)
            self.server = await asyncio.start_server(
                self._accept, "0.0.0.0", self.endpoint_port, ssl=server_context(self.directory)
            )
            self.endpoint_port = self.server.sockets[0].getsockname()[1]
        else:
            loop = asyncio.get_running_loop()

            def delivered(value):
                loop.call_soon_threadsafe(self._deliver, value)

            self.video = VideoBridge(delivered)
            await asyncio.to_thread(self.video.start)
        self.task(self._watch())
        if self.role == "patient":
            self.task(self._discover())
            if not self.environment:
                self.node_registry.start()

    def _deliver(self, value):
        if self.remote_status.get("status") == "approved":
            self.task(self.media.put(*value))

    async def _accept(self, reader, writer):
        if len(self.peers) >= 64:
            writer.close()
            return
        task = asyncio.current_task()
        self.connections.add(task)
        peer = Peer(
            reader,
            writer,
            self._request,
            clock=self.clock,
            video_sent=self._video_sent,
        ).start()
        self.peers[peer.id] = {"peer": peer, "selected": set()}
        try:
            await peer.closed.wait()
        finally:
            async with self.control_lock:
                self.viewer_peers.pop(peer.id, None)
                await self._close_viewers(peer.id)
                await self._release_owner(peer.id)
                if peer.id in self.access.surgeons:
                    await self.run(self.access.disconnect, peer.id)
                node = self.peer_nodes.pop(peer.id, None)
                if node:
                    self.nodes[node]["status"] = "offline"
                    for key, owner in self.owners.items():
                        if key.startswith(f"{node}:"):
                            owner.release()
                            owner.ready = False
            self.peers.pop(peer.id, None)
            await peer.close()
            self.connections.discard(task)

    async def _request(self, peer, method, params):
        if peer.id in self.viewer_peers:
            raise PermissionError("Native viewer connections are video-only")
        if method == "viewer.attach":
            if peer.id in self.access.surgeons or peer.id in self.peer_nodes:
                raise PermissionError("Use a separate native viewer connection")
            if len(self.viewer_peers) >= 32:
                raise RuntimeError("Too many native viewers")
            ticket = self.viewer_tickets.pop(params.get("ticket"), None)
            if ticket is None or ticket["expires"] < time.monotonic():
                raise PermissionError("Native viewer ticket expired or is invalid")
            owner, camera = ticket["owner"], ticket["camera"]
            if owner is not None:
                await self.run(self.access.require, owner)
                self.access.require(owner)
                if owner not in self.peers or camera not in self.peers[owner]["selected"]:
                    raise PermissionError("Camera is no longer selected")
            self.viewer_peers[peer.id] = {"owner": owner, "camera": camera}
            return True
        if method == "node.register":
            if self.environment:
                raise PermissionError("Simulation uses its own single node")
            node = self.node_registry.configs.get(params.get("id"))
            token = params.get("token")
            if (
                not node
                or not node.get("token")
                or not isinstance(token, str)
                or not secrets.compare_digest(node.get("token", ""), token)
            ):
                raise PermissionError("Node has not been enrolled")
            if params["id"] in self.peer_nodes.values():
                raise PermissionError("Node is already connected")
            self.peer_nodes[peer.id] = params["id"]
            self.nodes[params["id"]] = {**params["inventory"], "status": "online"}
            for key, owner in self.owners.items():
                if key.startswith(f"{params['id']}:"):
                    owner.release()
                    owner.ready = True
            return {"registered": True, "server_time": time.time()}
        if peer.id in self.peer_nodes:
            if method == "node.inventory":
                self.nodes[self.peer_nodes[peer.id]] = {**params["inventory"], "status": "online"}
                return True
            raise PermissionError("Unsupported node request")
        if method == "access.request":
            # Disconnect cleanup releases robot ownership and the old identity
            # under this lock. A returning service must wait for that cleanup.
            async with self.control_lock:
                return await self.run(
                    self.access.request,
                    peer.id,
                    params.get("name"),
                    params.get("robot", False),
                    params.get("credential"),
                )
        if method == "status":
            own = await self.run(self.access.status, peer.id)
            if own["status"] != "approved":
                return own
            return {**own, **self.inventory(), "server_time": time.time()}
        await self.run(self.access.require, peer.id)
        if method == "viewer.ticket":
            camera = params["camera"]
            if camera not in self.peers[peer.id]["selected"]:
                raise PermissionError("Select the camera before opening Holoviz")
            return await self._viewer_route(camera, peer.id)
        if method == "subscribe":
            cameras = {item["id"] for item in self.inventory()["cameras"]}
            selected = params.get("cameras", [])
            if not isinstance(selected, list) or len(selected) > 32 or not set(selected) <= cameras:
                raise ValueError("Unknown camera selection")
            self.peers[peer.id]["selected"] = set(selected)
            peer.clear_frames()
            await self._close_viewers(peer.id, cameras - set(selected))
            return True
        if method in {"robot.acquire", "robot.move", "robot.renew", "robot.release"}:
            async with self.control_lock:
                started = time.monotonic()
                result = await self._robot(peer.id, method, params)
                if method == "robot.move":
                    self.robot_timings.setdefault(params["id"], Samples()).add(
                        (time.monotonic() - started) * 1000
                    )
                return result
        raise PermissionError("Unsupported surgeon operation")

    async def _media_changed(self):
        if self.role == "patient":
            await self.streams.select(
                {
                    camera
                    for camera in self.media.connections.values()
                    if not camera.startswith("host:")
                }
            )

    async def _local_video(self, camera, header, payload):
        trace = mark(source(VideoHeader(**header)), "source_relay_ms")
        await self._publish(f"host:{camera}", header, payload, trace)

    def _video_sent(self, camera, trace, frame_bytes):
        feed = self.media.feeds.get(camera)
        if feed:
            feed.benchmark.add("transport_frame_bytes", frame_bytes)
            feed.benchmark.finish(trace, "send")

    async def _publish(self, camera, header, payload, trace=None):
        await self.media.put(camera, header, payload, {"trace": trace})
        native_owners = {
            item["owner"] for item in self.viewer_peers.values() if item["camera"] == camera
        }
        for key, item in list(self.peers.items()):
            viewer = self.viewer_peers.get(key)
            if viewer:
                owner = viewer["owner"]
                if viewer["camera"] != camera or (
                    owner is not None and self.access.status(owner)["status"] != "approved"
                ):
                    continue
            elif (
                not camera.startswith("host:")
                or key in native_owners
                or camera not in item["selected"]
                or self.access.status(key)["status"] != "approved"
            ):
                continue
            with contextlib.suppress(ConnectionError):
                item["peer"].event(
                    "video",
                    {"camera": camera, "header": header, "trace": mark(trace, "source_queue_ms")},
                    payload,
                    stream=camera,
                )

    def _viewer_ticket(self, camera, owner=None):
        cameras = {item["id"] for item in self.inventory()["cameras"]}
        if camera not in cameras:
            raise ValueError("Unknown camera")
        self.viewer_tickets = {
            key: value
            for key, value in self.viewer_tickets.items()
            if value["expires"] > time.monotonic()
        }
        if len(self.viewer_tickets) >= 32:
            raise RuntimeError("Too many pending native viewers")
        token = secrets.token_urlsafe(32)
        self.viewer_tickets[token] = {
            "camera": camera,
            "owner": owner,
            "expires": time.monotonic() + 30,
        }
        return token

    async def _viewer_route(self, camera, owner=None):
        node, device = camera.split(":", 1)
        if node == "host":
            cert = ssl.PEM_cert_to_DER_cert((self.directory / "endpoint.pem").read_text())
            return {
                "ticket": self._viewer_ticket(camera, owner),
                "host": "127.0.0.1",
                "port": self.endpoint_port,
                "fingerprint": hashlib.sha256(cert).hexdigest(),
            }
        config = self.node_registry.configs[node]
        connection = next(
            item["peer"] for key, item in self.peers.items() if self.peer_nodes.get(key) == node
        )
        host = (
            endpoint(config["address"])[0]
            if config.get("kind") == "service"
            else connection.writer.get_extra_info("peername")[0]
        )
        route = await self.node_call(
            node, "video.ticket", {"owner": owner or "patient", "camera": device, "id": camera}
        )
        if owner is not None:
            try:
                self.access.require(owner)
                if owner not in self.peers or camera not in self.peers[owner]["selected"]:
                    raise PermissionError("Camera is no longer selected")
            except PermissionError:
                await self.node_call(node, "video.revoke", {"owner": owner, "cameras": [device]})
                raise
        return {**route, "host": host}

    async def _close_viewers(self, owner, cameras=None):
        for node in set(self.peer_nodes.values()):
            devices = (
                None
                if cameras is None
                else [c.split(":", 1)[1] for c in cameras if c.startswith(node + ":")]
            )
            if devices == []:
                continue
            try:
                await self.node_call(
                    node, "video.revoke", {"owner": owner or "patient", "cameras": devices}
                )
            except (ConnectionError, RuntimeError, TimeoutError):
                pass  # Node disconnect also invalidates every direct ticket and stream.

        def matches(item):
            return item["owner"] == owner and (cameras is None or item["camera"] in cameras)

        self.viewer_tickets = {
            key: value for key, value in self.viewer_tickets.items() if not matches(value)
        }
        for key, viewer in list(self.viewer_peers.items()):
            if matches(viewer):
                self.viewer_peers.pop(key, None)
                if key in self.peers:
                    await self.peers[key]["peer"].close()

    async def _open_viewer(self, camera):
        if self.role == "surgeon":
            if self.remote_status.get("status") != "approved":
                raise PermissionError("Patient approval is required")
            inventory = self.remote_status
        else:
            inventory = self.inventory()
        device = next((item for item in inventory.get("cameras", []) if item["id"] == camera), None)
        if not device or device["status"] not in {"live", "stale"}:
            raise ValueError("Start the camera stream before opening Holoviz")
        if self.role == "surgeon":
            await self.action("view", {"cameras": sorted(self.selected | {camera})})
            route = await self.remote.call("viewer.ticket", {"camera": camera})
            if camera.startswith("host:"):
                route["host"] = endpoint(self.address, 7447)[0]
        else:
            route = await self._viewer_route(camera)
        await self.native.open(
            {
                "camera": camera,
                **route,
                "name": device["name"],
                "width": device["width"],
                "height": device["height"],
            }
        )
        if self.role == "surgeon" and self.remote_status.get("status") != "approved":
            await self.native.close(camera)
            raise PermissionError("Patient access was revoked")
        await self._sync_streams()
        return True

    async def _sync_streams(self):
        if self.role != "surgeon":
            return
        native = self.native.status()
        await self.streams.select(
            {
                camera
                for camera in self.selected
                if not camera.startswith("host:")
                and native.get(camera, {}).get("status") not in {"starting", "running"}
            }
        )

    def inventory(self):
        cameras, robots, nodes = [], [], []
        for key, node in self.nodes.items():
            nodes.append(
                {
                    "id": key,
                    "name": node.get("name", key),
                    "status": node.get("status"),
                    "sdk": node.get("sdk"),
                    "environment": node.get("environment"),
                    "simulation": node.get("simulation"),
                    "error": node.get("error", ""),
                    "connection": self.node_registry.configs.get(key, {}).get("kind", "ssh")
                    if key != "host"
                    else "local",
                    "address": self.node_registry.configs.get(key, {}).get("address", ""),
                    "paired": bool(self.node_registry.configs.get(key, {}).get("token")),
                }
            )
            for device in node.get("cameras", []):
                cameras.append(
                    {
                        field: value
                        for field, value in {
                            **device,
                            "id": f"{key}:{device['id']}",
                            "node": key,
                            "status": device.get("status", "stopped")
                            if node.get("status") == "online"
                            else "offline",
                        }.items()
                        if field
                        in {
                            "id",
                            "name",
                            "node",
                            "kind",
                            "status",
                            "error",
                            "frames",
                            "width",
                            "height",
                            "fps",
                            "modes",
                            "pixel_format",
                            "codec",
                            "qp",
                            "jpeg_quality",
                            "codecs",
                            "encoder_preset",
                        }
                    }
                )
            for device in node.get("robots", []):
                robot_id = f"{key}:{device['id']}"
                owner = self.owners.get(robot_id)
                surgeon = self.access.surgeons.get(owner.owner) if owner else None
                robots.append(
                    {
                        "id": robot_id,
                        "name": device["name"],
                        "kind": device["kind"],
                        "node": key,
                        "owner": surgeon.name if surgeon else None,
                        "owner_id": surgeon.id if surgeon else None,
                        "state": self.robot_state.get(robot_id),
                        "error": self.faults.get(robot_id, ""),
                        "status": node.get("status"),
                    }
                )
        return {"nodes": nodes, "cameras": cameras, "robots": robots}

    async def node_call(self, key, method, params=None):
        if key == "host":
            return await self.local.call(method, params)
        for peer_id, node_id in self.peer_nodes.items():
            if node_id == key:
                return await self.peers[peer_id]["peer"].call(method, params, timeout=3)
        raise ConnectionError("Node is offline")

    async def _robot(self, peer, method, params):
        await self.run(lambda: self.access.require(peer, robot=True))
        key = params["id"]
        if key not in {r["id"] for r in self.inventory()["robots"]}:
            raise ValueError("Robot is unavailable")
        node, device = key.split(":", 1)
        owner = self.owners.setdefault(key, Ownership())
        if owner.expired():
            await self._release(key)
        if method == "robot.acquire":
            token = await self.run(owner.acquire, peer)
            try:
                self.robot_state[key] = await self.node_call(
                    node, "robot.prepare", {"key": device, "token": token}
                )
            except Exception:
                owner.release()
                raise
            return {"token": token}
        token = params.get("token")
        await self.run(
            owner.validate, peer, token, params.get("sequence") if method == "robot.move" else None
        )
        if method == "robot.release":
            await self._release(key)
            return True
        if method == "robot.renew":
            return await self.node_call(node, method, {"key": device, "token": token})
        # Reject old input before it reaches the patient node's controller graph.
        sent = params.get("sent_at")
        if (
            type(sent) not in (float, int)
            or not math.isfinite(sent)
            or not -0.05 <= time.time() - sent <= 0.3
        ):
            raise ValueError("Robot input expired in transit")
        self.robot_state[key] = await self.node_call(
            node,
            method,
            {
                "key": device,
                "token": token,
                "sequence": params["sequence"],
                "command": params["command"],
                "sent_at": sent,
            },
        )
        return self.robot_state[key]

    async def _release(self, key):
        owner = self.owners[key]
        token = owner.token
        owner.release()
        owner.ready = False
        node, device = key.split(":", 1)
        try:
            await self.node_call(node, "robot.release", {"key": device, "token": token})
            owner.ready = True
            self.faults.pop(key, None)
        except Exception as exc:
            self.faults[key] = str(exc)
            LOG.warning("Robot hold failed: %s", exc)

    async def _release_owner(self, peer):
        for key, owner in self.owners.items():
            if owner.owner == peer:
                await self._release(key)

    async def connect(self, address, name, robot):
        if self.remote and self.remote_status.get("status") == "revoked":
            await self.remote.close()
        if self.remote and not self.remote.closed.is_set():
            raise ValueError("Disconnect before requesting another session")
        host, port, address = endpoint(address, 7447)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, int(port), ssl=client_context()), 10
            )
        except (OSError, TimeoutError) as exc:
            raise ConnectionError(
                f"Cannot connect to patient at {host}:{port}. "
                "Check that the patient service is running and use its connection port "
                "(default 7447), not the browser dashboard port."
            ) from exc
        try:
            pin_peer(writer, address, self.directory)
        except Exception:
            writer.close()
            raise

        async def reject(peer, method, params):
            raise PermissionError("Surgeon does not accept remote actions")

        async def event(peer, event_name, params, payload):
            if event_name == "video" and self.remote_status.get("status") == "approved":
                timing = peer.delivery(
                    params.get("timing"), frame_bytes=params.get("transport_bytes")
                )
                timing["trace"] = arrive(params.get("trace"), timing)
                self.video.put(params["camera"], params["header"], payload, timing)
            elif event_name == "revoked":
                self.remote_status = {"status": "revoked"}
                self.tokens.clear()
                await self.streams.close()
                await self.media.clear()
                await self.native.close()

        self.selected.clear()
        self.tokens.clear()
        self.sequences.clear()
        self.remote = Peer(reader, writer, reject, event, clock=self.clock).start()
        self.address = address
        self.timings = {key: Samples() for key in ("patient_round_trip_ms", "control_ack_ms")}
        self.robot_timings.clear()
        try:
            self.remote_status = await self.remote.call(
                "access.request", {"name": name, "robot": robot, "credential": self._identity()}
            )
        except BaseException:
            await self.remote.close()
            raise
        return self.remote_status

    def _identity(self):
        from telesurgery_core.configuration import load, save

        path = self.directory / "identity.yaml"
        identity = load(path)
        if not identity:
            identity = {"credential": secrets.token_urlsafe(32)}
            save(path, identity)
        return identity["credential"]

    async def status(self, *, metrics=False, device=None):
        statistics = {}
        if metrics:
            samples = {key: value.snapshot() for key, value in self.timings.items()}
            robots = {key: value.snapshot() for key, value in self.robot_timings.items()}

            def report():
                return {
                    "video": self.media.statistics(device) if device else self.media.statistics(),
                    "timings": {key: value.report() for key, value in samples.items()},
                    "robot_timings": {key: value.report() for key, value in robots.items()},
                }

            statistics = await asyncio.to_thread(report)
            if self.role == "patient":
                for node in set(self.peer_nodes.values()):
                    if device and not device.startswith(node + ":"):
                        continue
                    try:
                        reports = await self.node_call(
                            node,
                            "video.metrics",
                            {"camera": device.split(":", 1)[1] if device else None},
                        )
                        statistics["video"].update(
                            {f"{node}:{key}": value for key, value in reports.items()}
                        )
                    except (ConnectionError, RuntimeError, TimeoutError):
                        pass
        if self.role == "patient":
            inventory = self.inventory()
            for camera in inventory["cameras"]:
                if camera["id"] in self.streams.errors:
                    camera["error"] = self.streams.errors[camera["id"]]
            return {
                "role": self.role,
                "sdk": require_sdk().__version__,
                "endpoint_port": self.endpoint_port,
                "environment": self.environment,
                "simulation": self.simulation.status() if self.simulation else None,
                **inventory,
                "surgeons": await self.run(self.access.list),
                **statistics,
                "native_views": self.native.status(),
                "clock": self.clock.status(),
            }
        return {
            "role": self.role,
            "sdk": require_sdk().__version__,
            "patient": self.address,
            "session": {
                **self.remote_status,
                **(
                    {
                        "cameras": [
                            {
                                **camera,
                                **(
                                    {"error": self.streams.errors[camera["id"]]}
                                    if camera["id"] in self.streams.errors
                                    else {}
                                ),
                            }
                            for camera in self.remote_status["cameras"]
                        ]
                    }
                    if "cameras" in self.remote_status
                    else {}
                ),
            },
            "selected": sorted(self.selected),
            "video_pipeline_frames": self.video.sink.frames if self.video else 0,
            **statistics,
            "native_views": self.native.status(),
            "clock": self.clock.status(),
        }

    async def action(self, method, params):
        if method == "view.holoviz":
            return await self._open_viewer(params["camera"])
        if method == "view.browser":
            inventory = self.inventory() if self.role == "patient" else self.remote_status
            camera = next(
                (c for c in inventory.get("cameras", []) if c["id"] == params["camera"]), {}
            )
            if camera.get("codec", "h264") != "h264":
                raise ValueError("Use Holoviz for this stream format")
            await self.native.close(params["camera"])
            await self._sync_streams()
            return True
        if method == "view.close":
            await self.native.close(params["camera"])
            if self.role == "surgeon":
                await self.action("view.hide", {"cameras": [params["camera"]]})
            return True
        if method == "metrics.reset":
            device = params.get("device")
            if self.role == "patient":
                for node in set(self.peer_nodes.values()):
                    if device is None or device.startswith(node + ":"):
                        await self.node_call(
                            node,
                            "video.reset",
                            {"camera": device.split(":", 1)[1] if device else None},
                        )
            if device:
                self.robot_timings.pop(device, None)
                if device in self.media.feeds:
                    self.media.feeds[device].benchmark.reset()
                await self.native.reset_metrics(device)
                return True
            self.timings = {key: Samples() for key in self.timings}
            self.robot_timings.clear()
            for feed in self.media.feeds.values():
                feed.benchmark.reset()
            await self.native.reset_metrics()
            return True
        if self.role == "surgeon":
            if method == "connect":
                return await self.connect(
                    params["address"], params["name"], params.get("robot", False)
                )
            if method == "disconnect":
                if self.remote:
                    await self.remote.close()
                self.remote_status = {"status": "disconnected"}
                self.selected.clear()
                self.tokens.clear()
                await self.streams.close()
                await self.media.clear()
                await self.native.close()
                return True
            if not self.remote or self.remote.closed.is_set():
                raise ConnectionError("Connect to a patient first")
            if method in {"view", "view.hide"}:
                selected = set(params["cameras"])
                if method == "view.hide":
                    selected = self.selected - selected
                await self.remote.call("subscribe", {"cameras": sorted(selected)})
                for camera in self.selected - selected:
                    await self.native.close(camera)
                self.selected = selected
                await self._sync_streams()
                return True
            if method in {"robot.move", "robot.renew", "robot.release"}:
                received = time.time()
                started = time.monotonic()
                async with self.control_lock:
                    if method == "robot.move" and time.time() - received > 0.3:
                        raise TimeoutError("Robot input expired while waiting")
                    key = params["id"]
                    if key not in self.tokens:
                        if method != "robot.move":
                            return True
                        result = await self.run(lambda: {"id": key})
                        reply = await self.remote.call("robot.acquire", result)
                        self.tokens[key] = reply["token"]
                        self.sequences[key] = 0
                    self.sequences[key] += 1
                    outgoing = {
                        **params,
                        "token": self.tokens[key],
                        "sequence": self.sequences[key],
                        "sent_at": received + getattr(self, "clock_offset", 0.0),
                    }
                    outgoing = await self.run(lambda: outgoing)
                    try:
                        reply = await self.remote.call(method, outgoing, timeout=2)
                        result = await self.run(lambda value: value, reply)
                    except Exception:
                        self.tokens.pop(key, None)
                        raise
                    if method == "robot.release":
                        self.tokens.pop(key, None)
                    elif method == "robot.move":
                        elapsed = (time.monotonic() - started) * 1000
                        self.timings["control_ack_ms"].add(elapsed)
                        self.robot_timings.setdefault(key, Samples()).add(elapsed)
                    return result
            raise PermissionError("Unsupported surgeon action")
        if method == "access.approve":
            return await self.run(self.access.approve, params["id"], params.get("robot", False))
        if method in {"access.revoke", "access.reject"}:
            async with self.control_lock:
                affected = await self.run(self.access.revoke, params["id"])
                for peer_id in affected:
                    await self._close_viewers(peer_id)
                    item = self.peers.get(peer_id)
                    if item:
                        item["selected"].clear()
                        item["peer"].clear_frames()
                        item["peer"].event("revoked", {})
                    await self._release_owner(peer_id)
            return True
        if method == "robot.revoke":
            async with self.control_lock:
                if params["id"] in self.owners:
                    await self._release(params["id"])
            return True
        if method in {"camera.start", "camera.stop", "camera.rename"}:
            if method == "camera.stop":
                await self.native.close(params["id"])
                owners = {
                    item["owner"]
                    for item in [*self.viewer_peers.values(), *self.viewer_tickets.values()]
                    if item["camera"] == params["id"]
                }
                for owner in owners:
                    await self._close_viewers(owner, {params["id"]})
            node, device = params["id"].split(":", 1)
            result = await self.node_call(node, method, {**params, "id": device})
            self.nodes[node].update(result)
            return True
        if method == "node.add":
            return await self.node_registry.add(
                params["target"], int(params.get("sdk", 5)), params.get("environment")
            )
        if method == "node.environment":
            key = params["id"]
            if key == "host" or key not in self.node_registry.configs:
                raise ValueError("Choose an enrolled remote node")
            if self.node_registry.configs[key].get("kind") == "service":
                raise ValueError("Environment changes require an SSH-managed node")
            async with self.control_lock:
                if any(
                    name.startswith(key + ":") and owner.owner
                    for name, owner in self.owners.items()
                ):
                    raise ValueError("Release robot control before changing the node environment")
                result = await self.node_call(
                    key, "environment.set", {"environment": params.get("environment")}
                )
                self.nodes[key].update(result)
                for records in (self.owners, self.robot_state, self.robot_timings, self.faults):
                    for name in list(records):
                        if name.startswith(key + ":"):
                            records.pop(name)
            return True
        if method == "node.connect":
            return await self.node_registry.connect(params["address"], params["code"])
        if method == "node.remove":
            return await self.node_registry.remove(params["id"])
        raise ValueError("Unsupported patient action")

    async def _discover(self):
        while True:
            try:
                self.nodes["host"].update(await self.local.call("inventory"))
                if self.simulation and self.simulation.status()["status"] == "error":
                    self.nodes["host"].update(
                        status="error", error="Simulation stopped; see simulator.log"
                    )
                    for camera in list(self.local.local.workers):
                        await self.local.local.stop_camera(camera)
            except Exception:
                LOG.exception("Device discovery failed")
            await asyncio.sleep(2)

    async def _watch(self):
        tick = 0
        while True:
            try:
                if self.role == "patient":
                    async with self.control_lock:
                        for key, owner in self.owners.items():
                            if owner.expired():
                                await self._release(key)
                    await self.local.call("robot.expire")
                elif self.remote and not self.remote.closed.is_set() and tick % 5 == 0:
                    before = time.time()
                    started = time.monotonic()
                    reply = await self.remote.call("status")
                    state = await self.run(lambda value: value, reply)
                    self.timings["patient_round_trip_ms"].add((time.monotonic() - started) * 1000)
                    if "server_time" in state:
                        self.clock_offset = state["server_time"] - (before + time.time()) / 2
                    if (
                        state.get("status") != "approved"
                        and self.remote_status.get("status") == "approved"
                    ):
                        self.tokens.clear()
                        await self.streams.close()
                        await self.media.clear()
                        await self.native.close()
                    self.remote_status = state
                    if state.get("status") == "approved":
                        await self._sync_streams()
                elif self.role == "surgeon" and self.remote and self.remote.closed.is_set():
                    if self.remote_status.get("status") != "disconnected":
                        self.remote_status = {"status": "disconnected"}
                        self.tokens.clear()
                        await self.streams.close()
                        await self.media.clear()
                        await self.native.close()
            except Exception as exc:
                LOG.warning("Session update: %s", exc)
            tick += 1
            await asyncio.sleep(0.1)

    async def close(self):
        await self.native.close()
        LOG.info("Stopping application endpoint")
        if self.server:
            self.server.close()
        LOG.info("Stopping background tasks")
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        LOG.info("Closing peers")
        for item in list(self.peers.values()):
            await item["peer"].close()
        await asyncio.gather(*self.connections, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()
        if self.remote:
            await self.remote.close()
        LOG.info("Closing browser media")
        await self.streams.close()
        await self.media.clear()
        LOG.info("Closing device graphs")
        if self.video:
            await asyncio.to_thread(self.video.close)
        if self.local:
            await self.local.close()
        LOG.info("Closing simulation")
        if self.simulation:
            await self.simulation.close()
        await asyncio.to_thread(self.engine.close)
