# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Launch and stop local native windows; video never traverses this supervisor."""

import asyncio
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

from telesurgery_core.video.view import settings as zoom_settings

# A still older than this was written for an earlier request.
STILL_SECONDS = 3


def _replace(path, document):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document))
    temporary.replace(path)


class NativeViews:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.windows = {}
        self.zooms = {}
        self.displays = {}
        self.areas = {}  # camera -> priority area points, as last reported by the patient
        self.opening = set()
        self.lock = asyncio.Lock()

    def status(self):
        result = {}
        for camera, window in self.windows.items():
            if "finished" in window:
                result[camera] = window["finished"]
                continue
            path = window["config"].with_name("status.json")
            data = json.loads(path.read_text()) if path.exists() else {"status": "starting"}
            if window["process"].returncode is not None:
                if data["status"] != "error":
                    data["status"] = "closed"
                window["finished"] = data
                window["temporary"].cleanup()
            result[camera] = data
        for camera in self.opening:
            if camera not in self.windows:
                result[camera] = {"status": "starting"}
        return result

    async def open(self, config):
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("Holoviz needs a desktop display on this service's machine")
        camera = config["camera"]
        async with self.lock:
            if self.status().get(camera, {}).get("status") == "running":
                return True
            await self._close(camera)
            if sum(w["process"].returncode is None for w in self.windows.values()) >= 32:
                raise RuntimeError("Too many native camera windows")
            temporary = tempfile.TemporaryDirectory(prefix="telesurgery-viewer-")
            path = Path(temporary.name) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        **config,
                        "zoom": self.zooms.get(camera, zoom_settings()),
                        "display": self.displays.get(camera, {}) if config.get("depth") else {},
                        "region": self.areas.get(camera),
                    }
                )
            )
            path.chmod(0o600)
            self.directory.mkdir(parents=True, exist_ok=True)
            name = hashlib.sha256(camera.encode()).hexdigest()[:12]
            try:
                with (self.directory / f"{name}.log").open("w") as log:
                    process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "telesurgery_runtime.application.viewer",
                        str(path),
                        stdout=log,
                        stderr=asyncio.subprocess.STDOUT,
                    )
            except BaseException:
                temporary.cleanup()
                raise
            self.windows[camera] = {
                "process": process,
                "config": path,
                "temporary": temporary,
                "region": self.areas.get(camera),
            }
            window = self.windows[camera]
        try:
            # First neural viewing can download and build a GPU-specific engine.
            timeout = 600 if config.get("codec") == "surgical-tokenizer" else 20
            async with asyncio.timeout(timeout):
                while True:
                    if self.windows.get(camera) is not window:
                        raise RuntimeError("Holoviz was closed during startup")
                    status = self.status()[camera]
                    if status["status"] == "running":
                        return True
                    if status["status"] in {"error", "closed"}:
                        raise RuntimeError(status.get("error", "Holoviz closed during startup"))
                    await asyncio.sleep(0.1)
        except BaseException:
            async with self.lock:
                if self.windows.get(camera) is window:
                    await self._close(camera)
            raise

    async def _close(self, camera):
        window = self.windows.pop(camera, None)
        if window is None:
            return
        process = window["process"]
        try:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        finally:
            window["temporary"].cleanup()

    async def reset_metrics(self, selected=None):
        async with self.lock:
            requests = []
            for camera, state in self.status().items():
                if state["status"] == "running" and (selected is None or selected == camera):
                    window = self.windows[camera]
                    path = window["config"].with_name("reset-metrics")
                    path.touch()
                    requests.append((path, window["process"]))
            async with asyncio.timeout(3):
                while any(
                    path.exists() and process.returncode is None for path, process in requests
                ):
                    await asyncio.sleep(0.05)

    async def display(self, camera, mode, distance=2.0, opacity=0.4):
        if (
            mode not in {"color", "depth", "overlay", "side"}
            or not all(
                type(value) in (int, float) and math.isfinite(value)
                for value in (distance, opacity)
            )
            or not (0 < distance <= 100 and 0 <= opacity <= 1)
        ):
            raise ValueError("Invalid depth display settings")
        async with self.lock:
            values = {"mode": mode, "distance": distance, "opacity": opacity}
            self.displays[camera] = values
            if camera in self.windows and self.status().get(camera, {}).get("status") in {
                "starting",
                "running",
            }:
                _replace(self.windows[camera]["config"].with_name("display.json"), values)
        return True

    async def zoom(self, camera, scale=1.0, x=0.5, y=0.5):
        values = zoom_settings(scale, x, y)
        async with self.lock:
            self.zooms[camera] = values
            if camera in self.windows and self.status().get(camera, {}).get("status") in {
                "starting",
                "running",
            }:
                _replace(self.windows[camera]["config"].with_name("zoom.json"), values)
        return values

    def regions(self, areas):
        """Give each open window its camera's priority area, so it can draw the outline.

        areas maps camera to points or None, as the patient reports them. A window is
        told only when its camera's area changes.
        """
        self.areas = {camera: points for camera, points in areas.items() if points}
        for camera, window in self.windows.items():
            points = self.areas.get(camera)
            if points == window.get("region") or "finished" in window:
                continue
            if window["process"].returncode is None:
                try:
                    _replace(window["config"].with_name("region.json"), {"points": points})
                except OSError:
                    continue  # The window is closing; a new one starts with the area.
            window["region"] = points

    def preview(self, camera):
        """A recent still of a camera open in Holoviz, or None until the window has one.

        The dashboard draws a priority area on it. Each call renews the request; the
        window stops producing stills soon after the calls stop.
        """
        window = self.windows.get(camera)
        if window is None or self.status().get(camera, {}).get("status") != "running":
            raise LookupError("This camera is not open in Holoviz")
        window["config"].with_name("preview-request").touch()
        path = window["config"].with_name("preview.jpg")
        try:
            if time.time() - path.stat().st_mtime > STILL_SECONDS:
                return None
            return path.read_bytes()
        except OSError:
            return None

    async def close(self, camera=None):
        async with self.lock:
            for key in list(self.windows) if camera is None else [camera]:
                await self._close(key)
