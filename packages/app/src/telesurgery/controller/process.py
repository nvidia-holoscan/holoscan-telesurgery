# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One local controller window per surgeon service."""

import asyncio
import json
import math
import os
import signal
import sys
import tempfile
from pathlib import Path

from telesurgery_core import configuration


class NativeController:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = asyncio.Lock()
        self.process = self.temporary = self.path = None
        self.finished = {"status": "closed"}

    def status(self):
        if self.process is None:
            return self.finished
        state = json.loads(self.path.read_text()) if self.path.exists() else {"status": "starting"}
        if self.process.returncode is not None and state["status"] != "error":
            state["status"] = "closed"
        return state

    async def open(
        self,
        server,
        robot=None,
        certificate=None,
        preferences=None,
        input_device=None,
        *,
        retain_control=False,
    ):
        preferences = preferences or {}
        if (
            not isinstance(preferences, dict)
            or len(preferences) > 512
            or any(
                not isinstance(key, str)
                or not key.endswith((":arm-speed", ":roll-speed", ":grip-speed"))
                or type(value) not in (int, float)
                or not math.isfinite(value)
                or not 1 <= value <= 100
                for key, value in preferences.items()
            )
        ):
            raise ValueError("Controller speeds must be percentages from 1 to 100")
        if input_device is not None and (
            not isinstance(input_device, dict)
            or set(input_device) != {"name", "ordinal", "count"}
            or not isinstance(input_device["name"], str)
            or not 1 <= len(input_device["name"]) <= 80
            or type(input_device["ordinal"]) is not int
            or type(input_device["count"]) is not int
            or not 0 <= input_device["ordinal"] < input_device["count"] <= 32
        ):
            raise ValueError("Invalid controller selection")
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("Native controls need a desktop display on this service's machine")
        async with self.lock:
            if self.status()["status"] in {"starting", "running"}:
                return True
            await self._close()
            self.temporary = tempfile.TemporaryDirectory(prefix="telesurgery-controller-")
            self.path = Path(self.temporary.name) / "status.json"
            config = self.path.with_name("config.json")
            config.write_text(
                json.dumps(
                    {
                        "server": server,
                        "robot": robot,
                        "certificate": certificate,
                        "status_path": str(self.path),
                        "generation": self.temporary.name,
                        "input": input_device,
                        "retain_control": retain_control,
                        "preferences": {**self.finished.get("preferences", {}), **preferences},
                    }
                )
            )
            config.chmod(0o600)
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                # The SDK's managed Python ships Tk without Xft on Linux.
                # Use the desktop Python/Tk build for antialiased system fonts;
                # Haply uses the distribution's python3-websocket package.
                python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable
                environment = dict(os.environ)
                environment["PYTHONPATH"] = os.pathsep.join(
                    filter(
                        None,
                        (
                            str(Path(__file__).resolve().parents[2]),
                            # Desktop Python needs the shared calibration configuration too.
                            str(Path(configuration.__file__).resolve().parents[1]),
                            environment.get("PYTHONPATH"),
                        ),
                    )
                )
                log_path = self.directory / "controller.log"
                with log_path.open("w") as log:
                    self.process = await asyncio.create_subprocess_exec(
                        python,
                        "-m",
                        "telesurgery.controller.window",
                        str(config),
                        stdout=log,
                        stderr=asyncio.subprocess.STDOUT,
                        env=environment,
                    )
                async with asyncio.timeout(10):
                    while True:
                        state = self.status()
                        if state["status"] == "running" and (
                            not retain_control or state.get("acquired") == robot
                        ):
                            return True
                        if state["status"] in {"error", "closed"}:
                            exit_code = self.process.returncode
                            raise RuntimeError(
                                state.get("error")
                                or "Native controller closed during startup"
                                + (f" (exit code {exit_code})" if exit_code is not None else "")
                                + f"; see {log_path}"
                            )
                        await asyncio.sleep(0.05)
            except BaseException:
                await self._close()
                raise

    async def _close(self, retain_control=False):
        if self.process and self.process.returncode is None:
            if retain_control:
                self.process.send_signal(signal.SIGUSR1)
            else:
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 10)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.finished = {**self.status(), "status": "closed"}
        self.process = None
        if self.temporary:
            self.temporary.cleanup()
        self.temporary = self.path = None

    async def close(self, *, retain_control=False, generation=None):
        async with self.lock:
            if generation is not None:
                state = self.status()
                if state.get("generation") != generation or state["status"] != "closed":
                    return None
            await self._close(retain_control)
            return self.finished
