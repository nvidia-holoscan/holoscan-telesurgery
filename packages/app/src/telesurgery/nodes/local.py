# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Local device inventory and independently supervised camera workers."""

import asyncio
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import zmq
import zmq.asyncio
from telesurgery.nodes.camera_settings import modes, select
from telesurgery.nodes.profiles import devices as profile_devices
from telesurgery.nodes.profiles import manual_devices
from telesurgery_core.adapters import camera_zoom
from telesurgery_core.adapters.realsense import enrich
from telesurgery_core.adapters.v4l2 import camera_devices
from telesurgery_core.configuration import load, save
from telesurgery_core.diagnostics.logs import read_log
from telesurgery_core.hsb import discover as discover_hsb
from telesurgery_core.transport.protocol import MAX_FRAME, decode_video
from telesurgery_core.transport.rpc import RpcClient
from telesurgery_core.video import region
from telesurgery_core.video.capabilities import region_supported, supported_codecs
from telesurgery_core.video.config import Config
from telesurgery_core.video.reference import KEYFRAME_SUFFIX

# A live stream confirms a priority area within a frame; allow for a slow one.
REGION_CONFIRM_SECONDS = 1.5


async def _terminate(process):
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 8)
        except TimeoutError:
            process.kill()
            await process.wait()


def discover(directory, simulation=None):
    if simulation:
        manifest = Path(simulation)
        try:
            data = json.loads(manifest.read_text())
        except FileNotFoundError:
            return [], []
        else:
            connections = load(directory / "connections.yaml")
            robots = [
                {**item, "connection_enabled": connections.get(item["id"], True)}
                for item in data["robots"]
            ]
            return data["cameras"], robots
    data = manual_devices(directory)
    cameras = camera_devices()
    enrich(cameras)
    # Listen to the vendor's board announcements; do not infer a camera from a ping.
    for address, receivers in discover_hsb().items():
        cameras.append(
            {
                "id": f"hsb-{address}-0",
                "name": "IMX274",
                "source": "imx274",
                "kind": "HSB",
                "hololink": address,
                "expander": 0,
                "receivers": receivers,
                "width": 1920,
                "height": 1080,
                "fps": 60,
            }
        )
    cameras.extend(data.get("cameras", []))
    for camera in cameras:
        if camera.get("source") == "imx274":
            camera["receivers"] = ["linux"]
            if camera.get("receiver") == "fusa":
                camera["receiver"] = "auto"
    robots = [*data.get("robots", []), *profile_devices(directory)]
    ids = [item["id"] for item in robots]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate robot id across profiles and devices.yaml")
    return cameras, robots


class LocalNode:
    def __init__(self, directory, publish, simulation=None):
        self.directory, self.publish, self.simulation = Path(directory), publish, simulation
        self.directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="telesurgery-")
        self.context = zmq.asyncio.Context()
        self.cameras, self.robots, self.workers = {}, {}, {}
        self.board_initialized = set()
        self.seen_hsb = {}
        self.mutation = asyncio.Lock()
        self.settings_path = self.directory / "streams.yaml"
        self.settings = load(self.settings_path)
        # Priority areas live in memory only: a node restart returns to uniform quality.
        self.regions, self.region_errors = {}, {}
        self.region_revision = 0
        self.region_capable = False
        self.region_waiting = set()  # cameras whose set_region call is awaiting the encoder

    async def refresh(self):
        cameras, robots = await asyncio.to_thread(discover, self.directory, self.simulation)
        present = cameras or self.seen_hsb or self.workers
        codecs = await asyncio.to_thread(supported_codecs) if present else []
        capable = bool(set(codecs) & set(region.VIDEO_CODECS)) and await asyncio.to_thread(
            region_supported
        )
        # Nothing below waits: a stream changed during this refresh always finds its
        # camera with the settings it is running with, never a half-built entry.
        names = load(self.directory / "names.yaml")
        now = time.monotonic()
        for item in cameras:
            if item["kind"] == "HSB":
                self.seen_hsb[item["id"]] = (now, item)
        self.seen_hsb = {
            key: value
            for key, value in self.seen_hsb.items()
            if now - value[0] < 15 or key in self.workers
        }
        discovered = {item["id"]: item for item in cameras}
        discovered.update({key: value[1] for key, value in self.seen_hsb.items()})
        # Keep a disconnected worker visible so it can be stopped or retried.
        discovered.update(
            {
                key: self.cameras[key]
                for key in self.workers
                if key not in discovered and key in self.cameras
            }
        )
        self.cameras = {
            key: {**item, "name": names.get(key, item["name"])} for key, item in discovered.items()
        }
        if not self.cameras:
            codecs = []
        self.region_capable = capable and bool(self.cameras)
        for key, camera in self.cameras.items():
            camera["codecs"] = codecs
            if camera.get("codec", Config.codec) not in codecs and codecs:
                camera["codec"] = codecs[0]
            camera["modes"] = modes(camera)
            saved = self.settings.get(key)
            if (
                camera.get("source") == "imx274"
                and isinstance(saved, dict)
                and saved.get("receiver") == "fusa"
                and "fusa" not in camera.get("receivers", ["linux"])
            ):
                # Preserve resolution, codec and quality when loading a stream
                # saved with the former receiver; subsequent saves use Linux.
                saved = {**saved, "receiver": "auto"}
            try:
                camera.update(select(camera, saved))
            except ValueError:
                pass  # A reconnected device may no longer advertise the saved mode.
        self.robots = {item["id"]: item for item in robots}

    def inventory(self):
        cameras = []
        for key, camera in self.cameras.items():
            worker = self.workers.get(key)
            status, error = "stopped", ""
            if worker:
                path = worker["settings"].with_suffix(".error")
                try:
                    worker["encoding_error"] = path.read_text()[:1200]
                except FileNotFoundError:
                    worker["encoding_error"] = ""
                error = worker.get("error", "")
                status = (
                    "error"
                    if error
                    else (
                        "live"
                        if time.monotonic() - worker["updated"] < 2
                        else "starting"
                        if not worker["frames"]
                        else "stale"
                    )
                )
            cameras.append(
                {
                    **camera,
                    "status": status,
                    "error": error,
                    "encoding_error": worker["encoding_error"] if worker else "",
                    **self._region_state(key, camera, worker),
                    **(
                        {"codec": worker["active_codec"]}
                        if worker and "active_codec" in worker
                        else {}
                    ),
                    "frames": worker["frames"] if worker else 0,
                }
            )
        return {
            "name": socket.gethostname(),
            "cameras": cameras,
            "robots": list(self.robots.values()),
        }

    def _region_state(self, key, camera, worker):
        """What a camera reports about its priority area.

        region_supported: this camera's encoder can take an area at all.
        region_unavailable: why it cannot be used right now, although supported.
        region / region_by: the area the encoder confirmed, and who chose it.
        """
        status = (
            region.read_status(worker["settings"].with_suffix(region.STATUS_SUFFIX))
            if worker
            else {}
        )
        saved = self.regions.get(key)
        if (
            saved
            and key not in self.region_waiting  # that call reports and cleans up its own failure
            and status.get("error")
            and status.get("revision") == saved["revision"]
        ):
            # The encoder refused it: return to uniform quality rather than show an
            # outline the picture does not follow.
            self.region_errors[key] = status["error"]
            self._request_region(key, None)
            saved = None
        # A running encoder whose settings allow an area, and which still cannot take
        # one, knows better than the node's probe.
        refused = status.get("supported") is False and status.get("blocked") == ""
        supported = self.region_capable and not refused
        reason = ""
        if supported:
            # The active encoder's settings first: a pending change has not taken over yet.
            reason = status.get("blocked") or region.unavailable(
                camera.get("codec", Config.codec), camera.get("encoder_extra", "")
            )
            if not reason and key in self.region_errors:
                reason = "the encoder could not apply it; restart the stream to try again"
        applied = bool(
            saved
            and supported
            and not reason
            and status.get("revision") == saved["revision"]
            and not status.get("error")  # refused: the encoder does not have it
        )
        return {
            "region_supported": supported,
            "region_unavailable": reason,
            "region": saved["points"] if applied else None,
            "region_by": saved["by"] if applied else "",
        }

    def _request_region(self, key, saved):
        """Record a camera's area (None clears it) and hand it to a running worker."""
        self.region_revision += 1
        if saved is None:
            self.regions.pop(key, None)
        else:
            saved = self.regions[key] = {**saved, "revision": self.region_revision}
        worker = self.workers.get(key)
        if worker:
            region.write_request(
                worker["settings"].with_suffix(region.REQUEST_SUFFIX),
                self.region_revision,
                saved["points"] if saved else None,
            )
        return self.region_revision

    async def set_region(self, key, points, by=""):
        """Concentrate a camera's picture quality in one area; None returns to uniform."""
        async with self.mutation:
            if key not in self.cameras:
                raise ValueError("Camera is unavailable")
            if points is None:
                if key in self.regions:
                    self._request_region(key, None)
                return
            points = region.validate(points)
            if not isinstance(by, str) or len(by) > 80:
                raise ValueError("Invalid name")
            worker = self.workers.get(key)
            state = self._region_state(key, self.cameras[key], worker)
            if not state["region_supported"]:
                raise ValueError("This camera's encoder cannot use a priority area")
            if state["region_unavailable"]:
                raise ValueError(f"Priority area unavailable: {state['region_unavailable']}")
            if worker is None or worker.get("error"):
                raise ValueError("Start the stream before choosing a priority area")
            previous = self.regions.get(key)
            revision = self._request_region(key, {"points": points, "by": by})
            path = worker["settings"].with_suffix(region.STATUS_SUFFIX)
            deadline = time.monotonic() + REGION_CONFIRM_SECONDS
            # A status poll must not answer the encoder's reply before this call reads it.
            self.region_waiting.add(key)
            try:
                # The worker applies it on its next frame; answer once the encoder has it.
                while (status := region.read_status(path)).get("revision") != revision:
                    if time.monotonic() >= deadline or self.workers.get(key) is not worker:
                        self._request_region(key, previous)
                        raise TimeoutError(
                            "The stream did not confirm the priority area; "
                            "check that the camera is delivering frames"
                        )
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                # A dropped connection cancels this call: its caller gets no reply, so the
                # change must not stay in effect.
                self._request_region(key, previous)
                raise
            finally:
                self.region_waiting.discard(key)
            if status.get("error"):
                self.region_errors[key] = status["error"]
                self._request_region(key, None)
                raise RuntimeError(
                    f"The encoder could not apply the priority area: {status['error']}"
                )

    async def rename(self, key, name):
        if key not in self.cameras or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Unknown camera or invalid name")
        path = self.directory / "names.yaml"
        names = load(path)
        names[key] = name.strip()
        save(path, names)
        self.cameras[key]["name"] = name.strip()

    async def camera_log(self, key):
        if key not in self.cameras:
            raise ValueError("Camera is unavailable")
        slug = hashlib.sha256(key.encode()).hexdigest()[:12]
        return await asyncio.to_thread(read_log, self.directory / f"camera-{slug}.log")

    async def zoom_camera(self, key, value):
        async with self.mutation:
            if key not in self.cameras:
                raise ValueError("Camera is unavailable")
            camera = self.cameras[key]
            camera["camera_zoom"] = await asyncio.to_thread(
                camera_zoom.set_value, camera["source"], value
            )

    async def start_camera(self, key, settings=None):
        async with self.mutation:
            if key not in self.cameras:
                raise ValueError("Camera is unavailable")
            camera = self.cameras[key]
            selected = select(camera, settings)
            follows = selected["codec"] in region.VIDEO_CODECS
            if (
                key in self.regions
                and follows
                and region.unavailable(selected["codec"], selected["encoder_extra"])
            ):
                raise ValueError(
                    "Clear the priority area before turning on adaptive quantization "
                    "(aq, temporalaq)"
                )
            if key in self.workers:
                if not self.workers[key].get("error"):
                    changed = {k for k in selected if selected[k] != camera.get(k, "")}
                    if changed - {
                        "codec",
                        "rate_control",
                        "bitrate_mbps",
                        "qp",
                        "jpeg_quality",
                        "encoder_preset",
                        "encoder_extra",
                    }:
                        raise ValueError("Stop this stream before changing its capture settings")
                    if key in self.regions and not follows:
                        # The new format cannot follow an area; do not keep one it ignores.
                        self._request_region(key, None)
                    path = self.workers[key]["settings"]
                    if changed or path.with_suffix(".error").exists():
                        document = json.loads(path.read_text())
                        document["camera"].update(selected)
                        temporary = path.with_suffix(".tmp")
                        temporary.write_text(json.dumps(document))
                        temporary.replace(path)
                        self.settings[key] = selected
                        save(self.settings_path, self.settings)
                        camera.update(selected)
                        self.region_errors.pop(key, None)
                    return
                await self._stop(key)
            if key in self.regions and not follows:
                self._request_region(key, None)
            if camera.get("control_uri"):

                def configure():
                    with closing(RpcClient(camera["control_uri"], timeout=10)) as client:
                        client.send(
                            {
                                "jsonrpc": "2.0",
                                "method": "camera.configure",
                                "params": {
                                    "id": key,
                                    "width": selected["width"],
                                    "height": selected["height"],
                                    "depth": selected["depth"],
                                },
                            }
                        )

                await asyncio.to_thread(configure)
            config = {
                name: value for name, value in camera.items() if name in Config.__dataclass_fields__
            }
            config.update(selected)
            if config.get("source") == "imx274":
                board = config.get("hololink", "192.168.0.2")
                config["skip_reset"] = board in self.board_initialized
                self.board_initialized.add(board)
            slug = hashlib.sha256(key.encode()).hexdigest()[:12]
            endpoint = f"ipc://{self.temp.name}/{slug}.sock"
            settings = Path(self.temp.name) / f"{slug}.json"
            settings.with_suffix(".error").unlink(missing_ok=True)
            settings.with_suffix(region.STATUS_SUFFIX).unlink(missing_ok=True)
            self.region_errors.pop(key, None)
            if saved := self.regions.get(key):
                # A restarted stream keeps the area chosen for this camera.
                region.write_request(
                    settings.with_suffix(region.REQUEST_SUFFIX), saved["revision"], saved["points"]
                )
            else:
                settings.with_suffix(region.REQUEST_SUFFIX).unlink(missing_ok=True)
            settings.write_text(
                json.dumps(
                    {
                        "camera": asdict(Config(**config)),
                        "endpoint": endpoint,
                        "parent": os.getpid(),
                    }
                )
            )
            log = (self.directory / f"camera-{slug}.log").open("wb")
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "telesurgery_runtime.application.video",
                    str(settings),
                    stdout=log,
                    stderr=log,
                )
            finally:
                log.close()
            stream = self.context.socket(zmq.SUB)
            stream.setsockopt(zmq.SUBSCRIBE, b"")
            stream.setsockopt(zmq.RCVHWM, 2)
            stream.setsockopt(zmq.LINGER, 0)
            stream.setsockopt(zmq.MAXMSGSIZE, MAX_FRAME)
            stream.connect(endpoint)
            worker = {
                "process": process,
                "socket": stream,
                "updated": 0.0,
                "frames": 0,
                "settings": settings,
                "started": time.monotonic(),
            }
            self.workers[key] = worker
            worker["reader"] = asyncio.create_task(self._frames(key, worker))
            worker["watcher"] = asyncio.create_task(self._watch(key, worker, slug))
            self.settings[key] = selected
            save(self.settings_path, self.settings)
            self.cameras.setdefault(key, camera).update(selected)

    def request_keyframe(self, key):
        """Ask a running camera's encoder for an IDR; its worker polls for this file."""
        worker = self.workers.get(key)
        if worker is not None and not worker.get("error"):
            try:
                worker["settings"].with_suffix(KEYFRAME_SUFFIX).touch()
            except OSError:
                pass  # The worker is shutting down; its replacement starts with an IDR.

    async def _frames(self, key, worker):
        try:
            while True:
                header, payload = decode_video(await worker["socket"].recv_multipart())
                worker["updated"], worker["frames"] = time.monotonic(), worker["frames"] + 1
                worker["active_codec"] = header.codec
                await self.publish(key, asdict(header), payload)
        except (ValueError, zmq.ZMQError) as exc:
            worker["error"] = str(exc)

    async def _watch(self, key, worker, slug):
        process = worker["process"]
        while process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 30)
            except TimeoutError:
                # The first neural frame may need model download and engine building.
                if (
                    not worker["frames"]
                    and self.cameras[key].get("codec") == "surgical-tokenizer"
                    and time.monotonic() - worker.get("started", 0) < 600
                ):
                    continue
                if time.monotonic() - worker["updated"] >= 30:
                    worker["error"] = (
                        "No camera frames received for 30 seconds. Check the camera logs."
                    )
                    await _terminate(process)
        if self.workers.get(key) is worker:
            log = self.directory / f"camera-{slug}.log"
            worker.setdefault(
                "error", f"Camera exited ({process.returncode}): " + read_log(log)["text"][-1200:]
            )

    async def _stop(self, key):
        worker = self.workers.pop(key, None)
        if worker is None:
            return

        async def cleanup():
            try:
                await _terminate(worker["process"])
            finally:
                for task in (worker["reader"], worker["watcher"]):
                    task.cancel()
                try:
                    await asyncio.gather(
                        worker["reader"], worker["watcher"], return_exceptions=True
                    )
                finally:
                    worker["socket"].close()
                    for suffix in (".error", region.REQUEST_SUFFIX, region.STATUS_SUFFIX):
                        worker["settings"].with_suffix(suffix).unlink(missing_ok=True)

        # Cancellation during node disconnect must not orphan a camera/socket;
        # an open socket would also block context termination indefinitely.
        task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def stop_camera(self, key):
        async with self.mutation:
            await self._stop(key)

    async def close(self):
        for key in list(self.workers):
            await self.stop_camera(key)
        self.context.term()
        self.temp.cleanup()
