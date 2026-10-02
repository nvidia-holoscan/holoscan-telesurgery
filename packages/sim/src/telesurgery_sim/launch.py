# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Start one Isaac Sim process for all cameras and the robot in a selected room."""

import asyncio
import os
import secrets
import socket
import time
from pathlib import Path

from telesurgery_core.diagnostics.logs import read_log
from telesurgery_sim.presets import PRESETS


class Simulation:
    def __init__(self, environment, directory, *, gui=False):
        if environment not in PRESETS:
            raise ValueError("Unknown simulation environment")
        self.environment, self.directory = environment, Path(directory)
        self.gui = gui
        self.process = None
        self.started = None
        self.name = "telesurgery-sim-" + secrets.token_hex(5)

    async def start(self):
        self.started = time.monotonic()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o2775)
        display = []
        if self.gui:
            if not os.environ.get("DISPLAY"):
                raise RuntimeError("--sim-gui needs a desktop display on the simulation host")
            display = ["-e", "DISPLAY", "-v", "/tmp/.X11-unix:/tmp/.X11-unix:ro"]
            auth = Path(os.environ.get("XAUTHORITY", Path.home() / ".Xauthority"))
            if auth.is_file():
                # Isaac Sim uses its own UID; share only with the added host group.
                shared_auth = self.directory / ".xauthority"
                shared_auth.touch(mode=0o640)
                shared_auth.chmod(0o640)
                shared_auth.write_bytes(auth.read_bytes())
                display += ["-e", f"XAUTHORITY={shared_auth}"]
        (self.directory / "stop").unlink(missing_ok=True)
        cache = self.directory / "cache"
        cache.mkdir(exist_ok=True)
        cache.chmod(0o2775)
        shader_cache = self.directory / "shader-cache"
        shader_cache.mkdir(exist_ok=True)
        shader_cache.chmod(0o2775)
        manifest = self.directory / "devices.json"
        manifest.unlink(missing_ok=True)
        (self.directory / "progress").unlink(missing_ok=True)
        (self.directory / "result.json").unlink(missing_ok=True)
        root = (
            Path(os.environ["TELESURGERY_WORKSPACE"])
            if os.environ.get("TELESURGERY_WORKSPACE")
            else next(p for p in Path(__file__).resolve().parents if (p / "uv.lock").exists())
        )
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            api_port = reservation.getsockname()[1]
        # IPC camera endpoints are allocated by the simulator inside this shared directory.
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            self.name,
            "--gpus",
            "device=0",
            "--network",
            "host",
            "--group-add",
            str(os.getgid()),
            "--ulimit",
            "stack=33554432",
            "-e",
            "ACCEPT_EULA=Y",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            "NVIDIA_DRIVER_CAPABILITIES=all",
            "-e",
            "PYTHONPATH=/workspace/packages/core/src:/workspace/packages/sim/src:/workspace/runs/sim-deps",
            "-v",
            f"{root}/packages/core/src:/workspace/packages/core/src:ro",
            "-v",
            f"{root}/packages/sim/src:/workspace/packages/sim/src:ro",
            "-v",
            f"{root}/runs/sim-deps:/workspace/runs/sim-deps:ro",
            "-v",
            f"{self.directory}:{self.directory}",
            "-v",
            f"{cache}:/isaac-sim/.cache",
            "-v",
            f"{shader_cache}:/isaac-sim/kit/cache",
            *display,
            "--entrypoint",
            "/isaac-sim/python.sh",
            "nvcr.io/nvidia/isaac-sim:6.0.1",
            "/workspace/packages/sim/src/telesurgery_sim/scene.py",
            "--sim",
            self.environment,
            "--directory",
            str(self.directory),
            "--api-port",
            str(api_port),
            *(["--gui"] if self.gui else []),
        ]
        log_path = self.directory / "simulator.log"
        if log_path.exists():
            log_path.replace(self.directory / "simulator.previous.log")
        with log_path.open("wb") as log:
            self.process = await asyncio.create_subprocess_exec(*command, stdout=log, stderr=log)
        # The dashboard starts immediately; discovery fills in after assets and shaders load.
        return manifest

    async def close(self):
        if self.process is None:
            (self.directory / ".xauthority").unlink(missing_ok=True)
            return
        (self.directory / "stop").touch()
        try:
            await asyncio.wait_for(self.process.wait(), 15)
        except TimeoutError:
            stop = await asyncio.create_subprocess_exec(
                "docker",
                "stop",
                "-t",
                "5",
                self.name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await stop.wait()
            await self.process.wait()
        finally:
            (self.directory / ".xauthority").unlink(missing_ok=True)

    def log(self):
        return read_log(self.directory / "simulator.log")

    def status(self):
        manifest = self.directory / "devices.json"
        if self.process and self.process.returncode is not None:
            return {
                "status": "error",
                "error": self.log()["text"][-1200:],
            }
        if manifest.exists():
            return {"status": "ready", "gui": self.gui}
        progress = self.directory / "progress"
        return {
            "status": "loading",
            "gui": self.gui,
            "stage": progress.read_text() if progress.exists() else "Starting Isaac Sim",
            "elapsed": int(time.monotonic() - self.started) if self.started is not None else 0,
            "cameras": [name for _, name in PRESETS[self.environment]["cameras"]],
        }
