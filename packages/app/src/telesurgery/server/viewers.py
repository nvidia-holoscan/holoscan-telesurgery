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
from pathlib import Path


class NativeViews:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.windows = {}
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
            path.write_text(json.dumps(config))
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
            self.windows[camera] = {"process": process, "config": path, "temporary": temporary}
            try:
                async with asyncio.timeout(20):
                    while True:
                        status = self.status()[camera]
                        if status["status"] == "running":
                            return True
                        if status["status"] in {"error", "closed"}:
                            raise RuntimeError(status.get("error", "Holoviz closed during startup"))
                        await asyncio.sleep(0.1)
            except BaseException:
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
            if self.status().get(camera, {}).get("status") != "running":
                raise ValueError("Open Holoviz first")
            window = self.windows[camera]
            config = json.loads(window["config"].read_text())
            if not config.get("depth"):
                raise ValueError("This stream does not include depth")
            path = window["config"].with_name("display.json")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"mode": mode, "distance": distance, "opacity": opacity})
            )
            temporary.replace(path)
        return True

    async def close(self, camera=None):
        async with self.lock:
            for key in list(self.windows) if camera is None else [camera]:
                await self._close(key)
