# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Patient and surgeon services with a separate encrypted application endpoint."""

import asyncio
import contextlib
import logging
import math
import secrets
import time
from pathlib import Path

from telesurgery.controller.checkpoint_replay import CheckpointPlayback, validate_checkpoints
from telesurgery.controller.haply import BrowserHaply
from telesurgery.controller.haply import available as haply_available
from telesurgery.controller.process import NativeController
from telesurgery.controller.replay import (
    Catalog,
    FeedbackPlayback,
    Playback,
    Rendezvous,
    check_initial,
    read_rows,
)
from telesurgery.controller.replay_handoff import ReplayHandoff
from telesurgery.nodes.address import endpoint
from telesurgery.nodes.registry import NodeRegistry
from telesurgery.server.media import Media
from telesurgery.server.streams import DirectStreams
from telesurgery.server.viewers import NativeViews
from telesurgery_core.control.access import Access, Ownership
from telesurgery_core.diagnostics.benchmark import Samples
from telesurgery_core.diagnostics.clock import Clock
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.tls import client_context, pin_peer, server_context
from telesurgery_runtime.application.pipeline import Executor, VideoBridge
from telesurgery_runtime.backends.sdk import require_sdk

LOG = logging.getLogger(__name__)


class Application:
    def __init__(self, role, directory, endpoint_port=7447):
        self.role, self.directory = role, Path(directory)
        self.endpoint_port = endpoint_port
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.engine = Executor(role)
        self.media = Media(self._media_changed)
        self.access = Access(self.directory / "surgeons.yaml" if role == "patient" else None)
        self.native = NativeViews(self.directory / "viewers")
        self.controller = NativeController(self.directory / "controller")
        self.haply = BrowserHaply()
        self.replay_catalog = Catalog()
        self.replay_barrier = Rendezvous(self.replay_catalog)
        self.replays = {}
        self.controller_server = None
        self.controller_certificate = None
        self.peers, self.peer_nodes, self.nodes, self.owners = {}, {}, {}, {}
        self.replay_handoff = ReplayHandoff(self.owners, self._handoff_call)
        self.tokens, self.sequences, self.selected = {}, {}, set()
        self.control_lock = asyncio.Lock()
        self.tasks = set()
        self.connections = set()
        self.server = self.remote = self.video = None
        self.remote_status = {"status": "disconnected"}
        self.robot_state, self.faults = {}, {}
        self.address = ""
        self.timings = {}
        self.robot_timings = {}
        self.clock = Clock()
        self.streams = DirectStreams(self)
        self.node_registry = NodeRegistry(self)

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
            self.server = await asyncio.start_server(
                self._accept,
                "0.0.0.0",  # TLS and patient-approved peers. # nosec B104
                self.endpoint_port,
                ssl=server_context(self.directory),
                ssl_handshake_timeout=10,
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
            self._robot_feedback,
            clock=self.clock,
            max_payload=0,
        ).start()
        self.peers[peer.id] = {"peer": peer, "selected": set()}
        try:
            try:
                await asyncio.wait_for(peer.closed.wait(), 10)
            except TimeoutError:
                if (
                    peer.id in self.access.surgeons
                    or peer.id in self.peer_nodes
                    or any(item["peer"] == peer.id for item in self.node_registry.pending.values())
                ):
                    await peer.closed.wait()
        finally:
            async with self.control_lock:
                await self._close_viewers(peer.id)
                await self._release_owner(peer.id)
                if peer.id in self.access.surgeons:
                    await self.run(self.access.disconnect, peer.id)
                self.node_registry.disconnected(peer.id)
                node = self.peer_nodes.pop(peer.id, None)
                if node:
                    if node in self.nodes:
                        self.nodes[node]["status"] = "offline"
                    for key, owner in self.owners.items():
                        if key.startswith(f"{node}:"):
                            owner.release()
                            owner.ready = False
            self.peers.pop(peer.id, None)
            await peer.close()
            self.connections.discard(task)

    async def _robot_feedback(self, peer, name, params, payload):
        node = self.peer_nodes.get(peer.id)
        if name != "robot.feedback" or node is None:
            return
        for robot in self.nodes.get(node, {}).get("robots", []):
            feedback = params.get(robot["id"])
            if isinstance(feedback, dict):
                robot.update(feedback)

    async def _request(self, peer, method, params):
        if method == "node.request":
            if peer.id in self.access.surgeons or peer.id in self.peer_nodes:
                raise PermissionError("Use a separate node connection")
            return self.node_registry.request(peer, params)
        if method == "node.register":
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
            self.node_registry.disconnected(peer.id)
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
                return {"server_time": time.time()}
            raise PermissionError("Unsupported node request")
        if any(item["peer"] == peer.id for item in self.node_registry.pending.values()):
            raise PermissionError("Node approval is required")
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
        if method in {"replay.join", "replay.poll", "replay.cancel"}:
            async with self.control_lock:
                await self.run(lambda: self.access.require(peer.id, robot=True))
                key = params["id"]
                owner = self.owners.get(key)
                if owner is None:
                    raise ValueError("Robot is unavailable")
                await self.run(owner.validate, peer.id, params.get("token"))
                if method == "replay.cancel":
                    self.replay_barrier.cancel(params["run"], peer.id, key)
                    await self.replay_handoff.clear(key)
                    return True
                if method == "replay.poll":
                    barrier = self.replay_barrier.poll(
                        params["run"],
                        peer.id,
                        key,
                        self.owners,
                        finished=params.get("finished") is True,
                        checkpoint=params.get("checkpoint"),
                    )
                    robot = next((r for r in self.inventory()["robots"] if r["id"] == key), {})
                    if robot.get("stale") or robot.get("error") or robot.get("status") != "online":
                        raise RuntimeError("Replay stopped because robot feedback is unavailable")
                    state = robot.get("state", self.robot_state.get(key, {}))
                    handoff_context = self.replay_barrier.handoff(params["run"])
                    if params.get("fresh") is True or handoff_context:
                        # A motion acknowledgement may precede its physics step.
                        # Observe again before calculating a checkpoint correction.
                        state = await self._robot(peer.id, "robot.renew", params)
                    handoff = await self.replay_handoff.update(
                        handoff_context,
                        state,
                        finished=params.get("finished") is True,
                        take=params.get("take") is True,
                    )
                    return {
                        **barrier,
                        "state": state,
                        "handoff_done": handoff,
                    }
                robot = next((r for r in self.inventory()["robots"] if r["id"] == key), None)
                if robot is None or robot["status"] != "online":
                    raise ValueError("Robot is unavailable")
                await self.replay_handoff.clear(key)
                run = self.replay_barrier.join(params["recording"], robot, peer.id, owner.token)
                try:
                    await self.replay_handoff.prepare(self.replay_barrier.handoff(run))
                except Exception:
                    self.replay_barrier.cancel(run, peer.id, key)
                    raise
                return run
        if method in {"robot.acquire", "robot.move", "robot.renew", "robot.hold", "robot.release"}:
            async with self.control_lock:
                started = time.monotonic()
                barrier = None
                if method == "robot.move" and params.get("replay") is True:
                    barrier = self.replay_barrier.poll(
                        params["replay_run"], peer.id, params["id"], self.owners
                    )
                result = await self._robot(peer.id, method, params)
                if method == "robot.move":
                    self.robot_timings.setdefault(params["id"], Samples()).add(
                        (time.monotonic() - started) * 1000
                    )
                return {**result, "replay_barrier": barrier} if barrier else result
        raise PermissionError("Unsupported surgeon operation")

    async def _media_changed(self):
        if self.role == "patient":
            await self.streams.select(set(self.media.connections.values()))

    async def _viewer_route(self, camera, owner=None):
        node, device = camera.split(":", 1)
        connection = next(
            (item["peer"] for key, item in self.peers.items() if self.peer_nodes.get(key) == node),
            None,
        )
        if connection is None:
            raise ConnectionError("Node is offline")
        host = connection.writer.get_extra_info("peername")[0]
        if host in {"127.0.0.1", "localhost", "::1"} and owner is not None:
            # A local node's video listener is on the patient's machine, not the surgeon's.
            host = self.peers[owner]["peer"].writer.get_extra_info("sockname")[0]
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
        else:
            route = await self._viewer_route(camera)
        if camera in self.native.opening:
            raise RuntimeError("Holoviz is already opening")
        self.native.opening.add(camera)
        try:
            # Retire the browser path before the native decoder starts. The
            # opening status also rejects new offers throughout the handoff.
            await self.media.clear(camera)
            await self._media_changed()
            await self._sync_streams()
            await self.native.open(
                {
                    "camera": camera,
                    **route,
                    "name": device["name"],
                    "width": device["width"],
                    "height": device["height"],
                    "depth": device.get("depth", False),
                    "codec": device.get("codec", "h264"),
                }
            )
        finally:
            self.native.opening.discard(camera)
            await self._sync_streams()
        if self.role == "surgeon" and self.remote_status.get("status") != "approved":
            await self.native.close(camera)
            raise PermissionError("Patient access was revoked")
        await self._sync_streams()
        return True

    async def _sync_streams(self):
        if self.role != "surgeon":
            return
        available = {camera["id"] for camera in self.remote_status.get("cameras", [])}
        removed = self.selected - available
        if removed:
            self.selected.difference_update(removed)
            await self.remote.call("subscribe", {"cameras": sorted(self.selected)})
            for camera in removed:
                await self.native.close(camera)
        native = self.native.status()
        await self.streams.select(
            {
                camera
                for camera in self.selected
                if camera not in self.native.opening
                and native.get(camera, {}).get("status") not in {"starting", "running"}
            }
        )

    def inventory(self):
        cameras, robots, nodes = [], [], []
        connections = {
            node: self.peers[peer]["peer"].writer
            for peer, node in self.peer_nodes.items()
            if peer in self.peers
        }
        for key, node in self.nodes.items():
            config = self.node_registry.configs.get(key, {})
            writer = connections.get(key)
            ip = config.get("ip", "")
            if (
                writer
                and not writer.is_closing()
                and (address := writer.get_extra_info("peername"))
            ):
                ip = address[0]
            nodes.append(
                {
                    "id": key,
                    "name": node.get("name", key),
                    "ip": ip,
                    "status": node.get("status"),
                    "sdk": node.get("sdk"),
                    "uptime_s": node.get("uptime_s"),
                    "environment": node.get("environment"),
                    "simulation": node.get("simulation"),
                    "simulation_support": node.get("simulation_support"),
                    "error": node.get("error", ""),
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
                            "encoding_error",
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
                            "receiver",
                            "receivers",
                            "depth",
                            "depth_supported",
                            "depth_source",
                            "depth_fps",
                            "camera_zoom",
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
                        "controls": device.get("controls", {"inputs": [], "groups": {}}),
                        "simulation": device.get("simulation", False),
                        "feedback_age_ms": device.get("feedback_age_ms"),
                        "stale": device.get("stale", True) or node.get("status") != "online",
                        "node": key,
                        "owner": surgeon.name if surgeon else None,
                        "node_online": node.get("status") == "online",
                        **({"controller": device["controller"]} if "controller" in device else {}),
                        **(
                            {"connection_enabled": device["connection_enabled"]}
                            if "connection_enabled" in device
                            else {}
                        ),
                        "owner_id": surgeon.id if surgeon else None,
                        **(
                            {"reset_scene_blocked": self.scene_reset_blocked(robot_id)}
                            if device.get("controls", {}).get("reset_scene")
                            else {}
                        ),
                        "state": device.get("state"),
                        "error": self.faults.get(robot_id, device.get("error", "")),
                        "status": device.get("status", "online")
                        if node.get("status") == "online"
                        else "offline",
                    }
                )
        return {"nodes": nodes, "cameras": cameras, "robots": robots}

    def scene_reset_blocked(self, key):
        node, _ = key.split(":", 1)
        devices = self.nodes.get(node, {}).get("robots", [])
        scene = [
            f"{node}:{device['id']}"
            for device in devices
            if device.get("simulation") and device["kind"] == "versius-sim"
        ]
        if key in scene:
            for other in scene:
                owner = self.owners.get(other)
                if other != key and owner and (owner.owner is not None or not owner.ready):
                    return (
                        "Release control of all other arms and wait for them to stop "
                        "before resetting."
                    )
        return ""

    async def node_call(self, key, method, params=None):
        for peer_id, node_id in self.peer_nodes.items():
            if node_id == key:
                return await self.peers[peer_id]["peer"].call(
                    method,
                    params,
                    timeout=15
                    if method == "robot.start"
                    else 12
                    if method == "camera.stop"
                    else 5
                    if method in {"robot.release", "robot.disconnect"}
                    else 3,
                )
        raise ConnectionError("Node is offline")

    async def _handoff_call(self, key, method, params):
        if method == "handoff.acquire":
            return await self._robot(params["peer"], "robot.acquire", {"id": key})
        if method == "handoff.release":
            owner = self.owners[key]
            owner.validate(params["peer"], params["token"])
            result = await self._release(key)
            if not owner.ready:
                raise RuntimeError(self.faults[key])
            return result
        node, device = key.split(":", 1)
        result = await self.node_call(node, method, {"key": device, **params})
        self.robot_state[key] = result["state"] if method == "robot.replay_release" else result
        return result

    async def _robot(self, peer, method, params):
        await self.run(lambda: self.access.require(peer, robot=True))
        key = params["id"]
        robot = next((r for r in self.inventory()["robots"] if r["id"] == key), None)
        if robot is None:
            raise ValueError("Robot is unavailable")
        node, device = key.split(":", 1)
        owner = self.owners.setdefault(key, Ownership())
        if owner.expired():
            await self._release(key)
        if method == "robot.release" and owner.owner is None:
            result = await self._release(key)
            if not owner.ready:
                raise RuntimeError(self.faults[key])
            return result
        if method == "robot.acquire":
            if not owner.ready:
                raise RuntimeError(
                    "Previous stop was not confirmed; choose Retry hold on the patient dashboard. "
                    + self.faults.get(key, "")
                )
            token = await self.run(owner.acquire, peer)
            try:
                self.robot_state[key] = await self.node_call(
                    node, "robot.prepare", {"key": device, "token": token}
                )
            except Exception:
                owner.release()
                raise
            return {"token": token, "state": self.robot_state[key]}
        token = params.get("token")
        await self.run(
            owner.validate, peer, token, params.get("sequence") if method == "robot.move" else None
        )
        if method == "robot.release":
            result = await self._release(key)
            if not owner.ready:
                raise RuntimeError(self.faults[key])
            return result
        if method in {"robot.renew", "robot.hold"}:
            self.robot_state[key] = await self.node_call(
                node, method, {"key": device, "token": token}
            )
            return self.robot_state[key]
        # Reject old input before it reaches the patient node's controller graph.
        sent = params.get("sent_at")
        mode = params.get("mode", "jog")
        if mode not in {"step", "jog", "velocity", "home", "grip", "cartesian", "follow", "reset"}:
            raise ValueError("Unknown robot motion mode")
        if mode == "home" and not robot["controls"].get("home_deg"):
            raise ValueError("Home is not supported by this robot")
        if mode == "reset" and not (
            robot.get("simulation") and robot["controls"].get("reset_scene")
        ):
            raise ValueError("Scene reset is not supported by this robot")
        if mode == "reset" and (reason := self.scene_reset_blocked(key)):
            raise PermissionError(reason)
        if mode == "cartesian" and not robot["controls"].get("mira_cartesian"):
            raise ValueError("MIRA Cartesian jogging is not supported by this robot")
        if mode == "velocity" and not robot["controls"].get("joint_velocity"):
            raise ValueError("Joint velocity control is not supported by this robot")
        if mode == "follow" and not (
            robot.get("simulation") and robot["controls"].get("mira_follow")
        ):
            raise ValueError("MIRA target following is not supported by this robot")
        if mode == "grip" and not robot["controls"].get("grippers"):
            raise ValueError("Gripper control is not supported by this robot")
        if (
            type(sent) not in (float, int)
            or not math.isfinite(sent)
            or not -0.05 <= time.time() - sent <= 0.3
        ):
            raise ValueError("Robot input expired in transit")
        if mode == "reset":
            await self.replay_handoff.clear_scene(key)
            self.replay_barrier.released(key)
        if params.get("replay") is not True:
            await self.replay_handoff.clear(key)
            self.replay_barrier.released(key)
        self.robot_state[key] = await self.node_call(
            node,
            method,
            {
                "key": device,
                "token": token,
                "sequence": params["sequence"],
                "command": params["command"],
                "sent_at": sent,
                **({"speed_deg_s": params["speed_deg_s"]} if "speed_deg_s" in params else {}),
                **(
                    {"mode": mode}
                    if mode in {"velocity", "home", "grip", "cartesian", "follow", "reset"}
                    or robot["controls"].get("step_mode")
                    else {}
                ),
            },
        )
        return self.robot_state[key]

    async def _release(self, key):
        self.replay_barrier.released(key)
        owner = self.owners[key]
        token = owner.token
        owner.release()
        owner.ready = False
        node, device = key.split(":", 1)
        try:
            await self.replay_handoff.released(key)
            result = await self.node_call(node, "robot.release", {"key": device, "token": token})
            owner.ready = True
            self.faults.pop(key, None)
            return result
        except Exception as exc:
            reason = str(exc) or f"{type(exc).__name__}: robot stop was not confirmed"
            if self.faults.get(key) != reason:
                LOG.warning("Robot hold failed: %s", reason)
            self.faults[key] = reason

    async def _recover_holds(self):
        # Feedback recovery alone cannot confirm a failed Stop. Retry only hold,
        # with no owner; new motion always requires a fresh surgeon input.
        for robot in self.inventory()["robots"]:
            key = robot["id"]
            owner = self.owners.get(key)
            if (
                key in self.faults
                and owner
                and not owner.owner
                and robot["status"] == "online"
                and not robot["stale"]
            ):
                await self._release(key)

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
            if event_name == "revoked":
                self.remote_status = {"status": "revoked"}
                self.tokens.clear()
                await self.streams.close()
                await self.media.clear()
                await self.native.close()
                await self.controller.close()

        self.selected.clear()
        self.tokens.clear()
        self.sequences.clear()
        self.replays.clear()
        self.robot_state.clear()
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
                **inventory,
                "node_requests": self.node_registry.requests(),
                "surgeons": await self.run(self.access.list),
                **statistics,
                "native_views": self.native.status(),
                "view_zooms": dict(self.native.zooms),
                "view_displays": dict(self.native.displays),
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
            "view_zooms": dict(self.native.zooms),
            "view_displays": dict(self.native.displays),
            "native_controller": self.controller.status(),
            "haply_available": await asyncio.to_thread(haply_available),
            "replays": self.replay_catalog.list(),
            "clock": self.clock.status(),
        }

    async def action(self, method, params):
        if method in {"replay.start", "replay.read", "replay.cancel", "replay.heartbeat"}:
            return await self._replay_action(method, params)
        if method == "haply.read":
            if (
                self.role != "surgeon"
                or self.remote_status.get("status") != "approved"
                or not self.remote_status.get("robot")
            ):
                raise PermissionError("Robot control permission is required")
            robot = next(
                (r for r in self.remote_status.get("robots", []) if r["id"] == params.get("id")),
                None,
            )
            if not robot:
                raise ValueError("Robot is unavailable")
            reply = self.robot_state.get(robot["id"], {})
            if reply.get("sequence", -1) > (robot.get("state") or {}).get("sequence", -1):
                robot = {**robot, "state": reply}
            enabled = (
                robot.get("status") == "online"
                and not robot.get("stale")
                and not robot.get("error")
                and not robot.get("controls", {}).get("read_only")
                and (
                    not robot.get("owner") or robot.get("owner_id") == self.remote_status.get("id")
                )
            )
            return self.haply.read(
                robot, {**params, "enabled": params.get("enabled") is True and enabled}
            )
        if method == "controller.close":
            if params.get("retain_control") is True:
                closed = await self.controller.close(
                    retain_control=True,
                    **({"generation": params["generation"]} if "generation" in params else {}),
                )
                if closed is None:
                    return {"robot": None}
                # Consume the handoff before renewing, including failed renewals.
                # A refresh must not adopt an old window's lease a second time.
                key = closed.get("handoff")
                closed["handoff"] = None
                if closed.get("handoff_error"):
                    raise RuntimeError(closed["handoff_error"])
                if key:
                    state = await self.action("robot.renew", {"id": key})
                    return {"robot": key, "state": state, "controller": closed}
                return {"robot": None, "controller": closed}
            await self.controller.close()
            return True
        if method == "controller.open":
            if (
                self.role != "surgeon"
                or self.remote_status.get("status") != "approved"
                or not self.remote_status.get("robot")
            ):
                raise PermissionError("Robot control permission is required")
            if not self.controller_server:
                raise RuntimeError("Start the surgeon dashboard before opening native controls")
            selected = params.get("id")
            if selected and not any(
                r["id"] == selected for r in self.remote_status.get("robots", [])
            ):
                raise ValueError("Robot is unavailable")
            retain = params.get("retain_control") is True
            if retain:
                if selected not in self.tokens:
                    raise RuntimeError("Robot control is no longer acquired")
                await self.action("replay.cancel", {"id": selected})
                await self.action("robot.hold", {"id": selected})
            return await self.controller.open(
                self.controller_server,
                selected,
                self.controller_certificate,
                params.get("preferences"),
                params.get("input"),
                **({"retain_control": True} if retain else {}),
            )
        if method == "view.depth":
            inventory = self.inventory() if self.role == "patient" else self.remote_status
            device = next(
                (c for c in inventory.get("cameras", []) if c["id"] == params.get("camera")), {}
            )
            if not device.get("depth"):
                raise ValueError("This stream does not include depth")
            return await self.native.display(**params)
        if method == "view.zoom":
            inventory = self.inventory() if self.role == "patient" else self.remote_status
            if not any(c["id"] == params.get("camera") for c in inventory.get("cameras", [])):
                raise ValueError("Camera is unavailable")
            return await self.native.zoom(**params)
        if method == "view.holoviz":
            return await self._open_viewer(params["camera"])
        if method == "view.browser":
            inventory = self.inventory() if self.role == "patient" else self.remote_status
            camera = next(
                (c for c in inventory.get("cameras", []) if c["id"] == params["camera"]), {}
            )
            if camera.get("codec", "h264") not in {"h264", "surgical-tokenizer"}:
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
                await self.controller.close()
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
            if method in {
                "robot.acquire",
                "robot.move",
                "robot.renew",
                "robot.hold",
                "robot.release",
            }:
                received = time.time()
                started = time.monotonic()
                async with self.control_lock:
                    key = params["id"]
                    playback = self.replays.get(key)
                    if method == "robot.move":
                        if params.get("replay") is True and (
                            playback is None or params.get("replay_run") != playback.run
                        ):
                            raise RuntimeError("Replay input is no longer current")
                        if params.get("replay") is True and isinstance(playback, FeedbackPlayback):
                            # Materialize the next recorded input only while the
                            # dashboard is live and that exact input is pending.
                            # Its transit deadline starts when it can be sent.
                            playback.validate_request(params.get("mode", "jog"), params["command"])
                            received = time.time()
                        elif time.time() - received > 0.3:
                            raise TimeoutError("Robot input expired while waiting")
                    if method == "robot.acquire":
                        if key not in self.tokens:
                            reply = await self.remote.call("robot.acquire", {"id": key})
                            self.tokens[key] = reply["token"]
                            self.sequences[key] = 0
                            self.robot_state[key] = reply["state"]
                            return reply["state"]
                        method = "robot.renew"
                    if key not in self.tokens:
                        if method == "robot.release":
                            outgoing = await self.run(lambda: {"id": key})
                            reply = await self.remote.call(method, outgoing, timeout=7)
                            return await self.run(lambda: reply)
                        raise RuntimeError("Acquire robot control first")
                    self.sequences[key] += 1
                    outgoing = {
                        **params,
                        "token": self.tokens[key],
                        "sequence": self.sequences[key],
                        "sent_at": received + getattr(self, "clock_offset", 0.0),
                    }
                    outgoing = await self.run(lambda: outgoing)
                    try:
                        reply = await self.remote.call(
                            method,
                            outgoing,
                            timeout=7 if method in {"robot.release", "robot.hold"} else 2,
                        )
                    except Exception as exc:
                        if (
                            method == "robot.move"
                            and params.get("replay") is True
                            and isinstance(playback, CheckpointPlayback)
                            and (
                                str(exc) == "Robot input expired in transit"
                                or (
                                    playback.environment in {"franka", "versius"}
                                    and params.get("mode", "jog") == "jog"
                                    and str(exc)
                                    == "Controller rejected request: "
                                    "Cartesian physics feedback is unavailable or stale"
                                )
                            )
                        ):
                            # Both errors explicitly reject this motion. For a
                            # simulator rejection, the node confirms a hold
                            # before returning the error. Discard the old jog;
                            # the next tick observes physics and computes a new
                            # correction to the same checkpoint. Transport
                            # failures and unknown outcomes still stop replay.
                            state = await self.remote.call(
                                "robot.renew", {"id": key, "token": self.tokens[key]}
                            )
                            if self.replays.get(key) is not playback:
                                raise RuntimeError("Replay input is no longer current") from exc
                            if str(exc) != "Robot input expired in transit" and not isinstance(
                                state.get("cartesian_feedback"), dict
                            ):
                                raise exc
                            playback.acknowledge(state)
                            playback.input_display = None
                            playback.barrier = None
                            playback.renewed = time.monotonic()
                            self.robot_state[key] = state
                            return state
                        # Keep credentials for Stop unless the patient confirms
                        # our lease ended. Never replay failed motion.
                        with contextlib.suppress(Exception):
                            state = await self.remote.call("status")
                            if not any(
                                robot["id"] == key and robot.get("owner_id") == state.get("id")
                                for robot in state.get("robots", [])
                            ):
                                self.tokens.pop(key, None)
                        raise
                    result = await self.run(lambda value: value, reply)
                    if isinstance(result, dict):
                        barrier = result.pop("replay_barrier", None)
                        if barrier and isinstance(playback, FeedbackPlayback):
                            playback.barrier = barrier
                            playback.polled_at = time.monotonic()
                        self.robot_state[key] = result
                    if playback:
                        playback.renewed = time.monotonic()
                    if method == "robot.release":
                        self.tokens.pop(key, None)
                        self.robot_state.pop(key, None)
                        self.replays.pop(key, None)
                    elif method == "robot.move":
                        if (
                            params.get("replay") is True
                            and isinstance(playback, FeedbackPlayback)
                            and self.replays.get(key) is playback
                        ):
                            playback.acknowledge(result)
                        elapsed = (time.monotonic() - started) * 1000
                        self.timings["control_ack_ms"].add(elapsed)
                        self.robot_timings.setdefault(key, Samples()).add(elapsed)
                    return result
            raise PermissionError("Unsupported surgeon action")
        if method in {"camera.stop_all", "robot.disconnect_all"}:
            robots = method.startswith("robot.")
            inventory = self.inventory()
            offline = {node["id"] for node in inventory["nodes"] if node["status"] != "online"}
            failed = [
                {"name": node["name"], "error": "Node unreachable; action not confirmed"}
                for node in inventory["nodes"]
                if node["id"] in offline
            ]
            completed = []

            async def stop_device(item):
                try:
                    await self.action(
                        "robot.disconnect" if robots else "camera.stop", {"id": item["id"]}
                    )
                    completed.append(item["id"])
                except Exception as exc:
                    failed.append({"name": item["name"], "error": str(exc) or type(exc).__name__})

            await asyncio.gather(
                *(
                    stop_device(item)
                    for item in inventory["robots" if robots else "cameras"]
                    if item["id"].split(":", 1)[0] not in offline
                    and item["status"] != ("disconnected" if robots else "stopped")
                )
            )
            return {"completed": completed, "failed": failed}
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
        if method in {"robot.connect", "robot.disconnect"}:
            async with self.control_lock:
                key = params["id"]
                if method == "robot.disconnect" and key in self.owners and self.owners[key].owner:
                    await self._release(key)
                node, device = key.split(":", 1)
                result = await self.node_call(node, method, {"id": device})
                self.nodes[node].update(result)
                if method == "robot.disconnect":
                    if key in self.owners:
                        self.owners[key].release()
                        self.owners[key].ready = True
                    self.faults.pop(key, None)
                    self.robot_state.pop(key, None)
            return True
        if method == "robot.start":
            node, device = params["id"].split(":", 1)
            return await self.node_call(node, method, {"id": device})
        if method in {"camera.start", "camera.stop", "camera.rename", "camera.zoom"}:
            if method == "camera.stop":
                await self.native.close(params["id"])
                owners = {
                    key for key, item in self.peers.items() if params["id"] in item["selected"]
                }
                owners.add(None)
                for owner in owners:
                    await self._close_viewers(owner, {params["id"]})
            node, device = params["id"].split(":", 1)
            result = await self.node_call(node, method, {**params, "id": device})
            self.nodes[node].update(result)
            if method == "camera.zoom":
                return next(c["camera_zoom"] for c in result["cameras"] if c["id"] == device)
            return True
        if method in {"node.approve", "node.reject"}:
            return await self.node_registry.decide(params["id"], method == "node.approve")
        if method == "node.remove":
            return await self.node_registry.remove(params["id"])
        raise ValueError("Unsupported patient action")

    async def _replay_action(self, method, params):
        if (
            self.role != "surgeon"
            or self.remote_status.get("status") != "approved"
            or not self.remote_status.get("robot")
        ):
            raise PermissionError("Robot control permission is required")
        key = params["id"]
        if key not in self.tokens:
            self.replays.pop(key, None)
            raise PermissionError("Acquire robot control before replay")
        credentials = {"id": key, "token": self.tokens[key]}
        playback = self.replays.get(key)
        if method == "replay.heartbeat":
            if playback:
                playback.read_at = playback.clock()
            return True
        if method == "replay.cancel":
            if playback:
                self.replays.pop(key, None)
                await self.remote.call("replay.cancel", {**credentials, "run": playback.run})
            return True
        if method == "replay.start":
            if playback:
                raise RuntimeError("Stop the current replay first")
            robot = next((r for r in self.remote_status.get("robots", []) if r["id"] == key), None)
            if (
                robot is None
                or robot["status"] != "online"
                or robot.get("stale")
                or robot.get("error")
            ):
                raise ValueError("Robot is unavailable")
            path, manifest, role = self.replay_catalog.get(params["recording"], robot)
            state = await self.action("robot.renew", {"id": key})
            check_initial(
                state,
                manifest["streams"][role]["initial"],
                starting_scene=manifest.get("starting_scene", "Home"),
            )
            rows = await asyncio.to_thread(
                read_rows, path.parent / manifest["streams"][role]["file"]
            )
            if manifest["version"] == 2:
                validate_checkpoints(
                    rows, environment=manifest["environment"], device=manifest["device"]
                )
                if max((row.get("barrier", 0) for row in rows), default=0) != manifest.get(
                    "barriers", 0
                ):
                    raise ValueError("Replay stream has incomplete handoff barriers")
            run = await self.remote.call(
                "replay.join", {**credentials, "recording": params["recording"]}
            )
            playback_type = (
                FeedbackPlayback
                if robot["kind"] == "mira-sim" and manifest["device"] == "keyboard"
                else Playback
            )
            if manifest["version"] == 2:
                playback_type = CheckpointPlayback
            self.replays[key] = playback_type(robot, manifest, role, rows, run)
            return True
        if playback is None:
            raise RuntimeError("Replay stopped")
        try:
            feedback = isinstance(playback, FeedbackPlayback)
            if isinstance(playback, CheckpointPlayback) and playback.taking:
                if playback.clock() - playback.read_at > 0.3:
                    raise TimeoutError("Replay paused because the dashboard stopped polling")
            now = time.monotonic()
            if (
                not feedback
                or isinstance(playback, CheckpointPlayback)
                or playback.barrier is None
                or now - playback.polled_at >= 0.1
                or playback.finished
            ):
                barrier = await self.remote.call(
                    "replay.poll",
                    {
                        **credentials,
                        "run": playback.run,
                        "finished": playback.finished,
                        **(
                            {
                                "checkpoint": playback.checkpoint,
                                "fresh": True,
                                "take": playback.taking,
                            }
                            if isinstance(playback, CheckpointPlayback)
                            else {}
                        ),
                    },
                )
                if isinstance(playback, CheckpointPlayback) and "checkpoint" not in barrier:
                    raise RuntimeError(
                        "Patient service does not support checkpoint replay; "
                        "restart it with the updated code"
                    )
                if (
                    isinstance(playback, CheckpointPlayback)
                    and playback.independent_actions
                    and not barrier.get("independent_actions")
                ):
                    raise RuntimeError("Restart the patient service to support independent replay")
                if (
                    isinstance(playback, CheckpointPlayback)
                    and playback.requires_presented_needle
                    and not barrier.get("handoff_required")
                ):
                    raise RuntimeError("Restart the patient service to support needle transfer")
                if feedback:
                    playback.barrier, playback.polled_at = barrier, time.monotonic()
                    if isinstance(playback, CheckpointPlayback):
                        playback.renewed = time.monotonic()
            else:
                barrier = playback.barrier
            elapsed = barrier["elapsed"]
            if feedback and elapsed is not None:
                elapsed += time.monotonic() - playback.polled_at
            state = self.robot_state.get(key, {})
            if feedback:
                # Motion acknowledgements carry measured feedback too. The
                # slower inventory publication must not replace newer samples.
                state = max(
                    (state, barrier.get("state", {})),
                    key=lambda sample: sample.get("sequence", -1),
                )
            if (feedback and time.monotonic() - playback.renewed >= 0.5) or (
                not feedback
                and elapsed is not None
                and playback.index < len(playback.rows)
                and playback.rows[playback.index]["t"] <= elapsed
            ):
                state = await self.action("robot.renew", {"id": key})
                playback.renewed = time.monotonic()
            if isinstance(playback, CheckpointPlayback):
                playback.synchronized = barrier.get("checkpoint", 0)
                if playback.taking and "handoff_done" not in barrier:
                    raise RuntimeError("Restart the patient service to support independent replay")
                playback.handoff_done = barrier.get("handoff_done", False)
            result = playback.read(-1 if elapsed is None else elapsed, state)
            input_display = playback.display_input(result)
            if barrier["done"]:
                self.replays.pop(key, None)
            return {
                **result,
                "input": input_display if not barrier["done"] and elapsed is not None else None,
                "done": barrier["done"],
                "waiting": elapsed is None,
                "state": state,
                "feedback_paced": isinstance(playback, FeedbackPlayback),
                "run": playback.run,
            }
        except Exception:
            self.replays.pop(key, None)
            with contextlib.suppress(Exception):
                await self.remote.call("replay.cancel", {**credentials, "run": playback.run})
            raise

    async def _watch(self):
        tick = 0
        while True:
            try:
                if self.haply.reader and (
                    time.monotonic() - self.haply.last_read > 2
                    or self.remote_status.get("status") != "approved"
                ):
                    await asyncio.to_thread(self.haply.close)
                if self.role == "patient":
                    async with self.control_lock:
                        for key, owner in self.owners.items():
                            if owner.expired():
                                await self._release(key)
                        if tick % 20 == 0 and self.faults:
                            await self._recover_holds()
                elif self.remote and not self.remote.closed.is_set() and tick % 5 == 0:
                    before = time.time()
                    started = time.monotonic()
                    reply = await self.remote.call("status")
                    received = time.time()
                    state = await self.run(lambda value: value, reply)
                    self.timings["patient_round_trip_ms"].add((time.monotonic() - started) * 1000)
                    if "server_time" in state:
                        self.clock_offset = (
                            0.0
                            if self.clock.domain
                            and self.remote.relative_clock.domain == self.clock.domain
                            else state["server_time"] - (before + received) / 2
                        )
                    if (
                        state.get("status") != "approved"
                        and self.remote_status.get("status") == "approved"
                    ):
                        self.tokens.clear()
                        await self.streams.close()
                        await self.media.clear()
                        await self.native.close()
                        await self.controller.close()
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
                        await self.controller.close()
            except Exception as exc:
                LOG.warning("Session update: %s", exc)
            tick += 1
            await asyncio.sleep(0.1)

    async def close(self):
        await asyncio.to_thread(self.haply.close)
        await self.native.close()
        await self.controller.close()
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
        await asyncio.to_thread(self.engine.close)
