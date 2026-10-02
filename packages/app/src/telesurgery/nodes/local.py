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
from telesurgery_core.adapters.v4l2 import camera_devices
from telesurgery_core.configuration import load, save
from telesurgery_core.diagnostics.logs import read_log
from telesurgery_core.transport.protocol import MAX_RAW_VIDEO, decode_video
from telesurgery_core.transport.rpc import RpcClient
from telesurgery_core.video.capabilities import supported_codecs
from telesurgery_core.video.config import Config
from telesurgery_runtime.sdk import backend


def discover(directory, simulation=None):
    if simulation:
        manifest = Path(simulation)
        if manifest.exists():
            data = json.loads(manifest.read_text())
            return data["cameras"], data["robots"]
        return [], []
    cameras = camera_devices()
    # Listen to the vendor's board announcements; do not infer a camera from a ping.
    for address in backend("camera").discover():
        cameras.append(
            {
                "id": f"hsb-{address}-0",
                "name": "IMX274",
                "source": "imx274",
                "kind": "HSB",
                "hololink": address,
                "expander": 0,
                "width": 1920,
                "height": 1080,
                "fps": 60,
            }
        )
    data = load(directory / "devices.yaml")
    cameras.extend(data.get("cameras", []))
    return cameras, data.get("robots", [])


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

    async def refresh(self):
        cameras, robots = await asyncio.to_thread(discover, self.directory, self.simulation)
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
        codecs = await asyncio.to_thread(supported_codecs) if self.cameras else []
        for key, camera in self.cameras.items():
            camera["codecs"] = codecs
            if camera.get("codec", Config.codec) not in codecs and codecs:
                camera["codec"] = codecs[0]
            camera["modes"] = modes(camera)
            try:
                camera.update(select(camera, self.settings.get(key)))
            except ValueError:
                pass  # A reconnected device may no longer advertise the saved mode.
        self.robots = {item["id"]: item for item in robots}

    def inventory(self):
        cameras = []
        for key, camera in self.cameras.items():
            worker = self.workers.get(key)
            status, error = "stopped", ""
            if worker:
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
                    "frames": worker["frames"] if worker else 0,
                }
            )
        return {
            "name": socket.gethostname(),
            "cameras": cameras,
            "robots": list(self.robots.values()),
        }

    async def rename(self, key, name):
        if key not in self.cameras or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Unknown camera or invalid name")
        path = self.directory / "names.yaml"
        names = load(path)
        names[key] = name.strip()
        save(path, names)
        self.cameras[key]["name"] = name.strip()

    async def start_camera(self, key, settings=None):
        async with self.mutation:
            if key not in self.cameras:
                raise ValueError("Camera is unavailable")
            camera = self.cameras[key]
            selected = select(camera, settings)
            if key in self.workers:
                if not self.workers[key].get("error"):
                    if any(selected[k] != camera.get(k, "") for k in selected):
                        raise ValueError("Stop this stream before changing its settings")
                    return
                await self._stop(key)
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
                    "telesurgery_runtime.video",
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
            stream.setsockopt(zmq.MAXMSGSIZE, MAX_RAW_VIDEO)
            stream.connect(endpoint)
            worker = {"process": process, "socket": stream, "updated": 0.0, "frames": 0}
            self.workers[key] = worker
            worker["reader"] = asyncio.create_task(self._frames(key, worker))
            worker["watcher"] = asyncio.create_task(self._watch(key, worker, slug))
            self.settings[key] = selected
            save(self.settings_path, self.settings)
            self.cameras.setdefault(key, camera).update(selected)

    async def _frames(self, key, worker):
        try:
            while True:
                header, payload = decode_video(await worker["socket"].recv_multipart())
                worker["updated"], worker["frames"] = time.monotonic(), worker["frames"] + 1
                await self.publish(key, asdict(header), payload)
        except (ValueError, zmq.ZMQError) as exc:
            worker["error"] = str(exc)

    async def _watch(self, key, worker, slug):
        status = await worker["process"].wait()
        if self.workers.get(key) is worker:
            log = self.directory / f"camera-{slug}.log"
            worker["error"] = f"Camera exited ({status}): " + read_log(log)["text"][-1200:]

    async def _stop(self, key):
        worker = self.workers.pop(key, None)
        if worker is None:
            return
        process = worker["process"]
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 8)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (worker["reader"], worker["watcher"]):
            task.cancel()
        await asyncio.gather(worker["reader"], worker["watcher"], return_exceptions=True)
        worker["socket"].close()

    async def stop_camera(self, key):
        async with self.mutation:
            await self._stop(key)

    async def close(self):
        for key in list(self.workers):
            await self.stop_camera(key)
        self.context.term()
        self.temp.cleanup()
