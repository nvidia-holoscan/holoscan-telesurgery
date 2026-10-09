# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Explicit startup of the vendor MIRA daemon on its device node."""

import asyncio
import hashlib
import ipaddress
import json
import os
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from telesurgery_robots.mira.binary import checksum


class MiraController:
    # This is a vendor process, not a robot stop or a motion permission switch.
    label = "com.nvidia.telesurgery.robot"

    def __init__(self, spec, directory):
        self.spec, self.directory = spec, Path(directory).resolve()
        self.image = spec["controller"].get(
            "image",
            f"holoscan-telesurgery:{version('telesurgery-robots')}"
            f"-sdk{os.environ.get('TELESURGERY_SDK', '5')}",
        )
        self.identity = hashlib.sha256(f"{self.directory}:{spec['id']}".encode()).hexdigest()[:12]
        self.name = f"telesurgery-mira-{self.identity}"

    async def _docker(self, *args):
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT if args[0] == "logs" else asyncio.subprocess.PIPE,
        )
        try:
            output, error = await asyncio.wait_for(
                process.communicate(), 8 if args[0] == "run" else 2
            )
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode:
            message = (error or output).decode(errors="replace").strip()
            if args[0] == "inspect" and "no such object" in message.lower():
                return None
            raise RuntimeError(message or "Docker controller operation failed")
        return output.decode(errors="replace").strip()

    async def _inspect(self):
        output = await self._docker("inspect", self.name)
        if output is None:
            return None
        info = json.loads(output)[0]
        if info["Config"].get("Labels", {}).get(self.label) != self.identity:
            raise RuntimeError("Controller container belongs to another installation")
        return info

    async def status(self):
        try:
            info = await self._inspect()
            state = info["State"] if info else {}
            running = state.get("Running", False)
            error = state.get("Error", "")
            if not running and state.get("ExitCode"):
                error = error or f"Controller exited ({state['ExitCode']}); open Logs"
            return {
                "status": "running" if running else "error" if error else "stopped",
                "error": error,
            }
        except (OSError, RuntimeError, TimeoutError) as exc:
            return {"status": "unavailable", "error": str(exc)}

    def command(self):
        settings = self.spec["controller"]
        binary = Path(settings["executable"]).expanduser().resolve(strict=True)
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError("MIRA controller executable is not runnable")
        if settings.get("sha256") and checksum(binary) != settings["sha256"]:
            raise ValueError("MIRA API changed; restart the node to load the updated executable")
        uri = urlsplit(self.spec["uri"])
        if uri.scheme != "ws" or uri.hostname != "127.0.0.1" or not uri.port:
            raise ValueError("Managed MIRA API must use ws://127.0.0.1:PORT")
        interface = ipaddress.IPv4Address(settings["pod_interface"])
        if interface.is_unspecified or interface.is_multicast or interface.is_loopback:
            raise ValueError("Use the node's POD-facing IPv4 address")
        work = self.directory / f"controller-{self.identity}"
        work.mkdir(parents=True, exist_ok=True)
        return [
            "run",
            "--detach",
            "--pull",
            "never",
            "--name",
            self.name,
            "--restart",
            "no",
            "--label",
            f"{self.label}={self.identity}",
            "--log-driver",
            "local",
            "--log-opt",
            "max-size=5m",
            "--log-opt",
            "max-file=2",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--publish",
            f"127.0.0.1:{uri.port}:8081",
            "--publish",
            f"{interface}:10000:10000/udp",
            "--volume",
            f"{binary}:/opt/mira-api:ro",
            "--volume",
            f"{work}:/work",
            "--workdir",
            "/work",
            "--entrypoint",
            "/opt/mira-api",
            self.image,
        ]

    async def start(self):
        info = await self._inspect()
        if info and info["State"].get("Running"):
            return  # Repeated clicks or a node reconnect never restart an active controller.
        command = self.command()
        # Only an existing local image is used; do not download during robot startup.
        await self._docker("image", "inspect", self.image)
        if info:
            await self._docker("rm", self.name)
        await self._docker(*command)

    async def log(self):
        if not await self._inspect():
            return {"text": "Controller has not been started.", "updated_seconds_ago": None}
        # Docker may put the application's stderr in its own stderr stream.
        output = await self._docker("logs", "--tail", "100", "--timestamps", self.name)
        age = None
        if output:
            try:
                stamp = datetime.fromisoformat(
                    output.splitlines()[-1].split(" ", 1)[0].replace("Z", "+00:00")
                )
                age = max(0, round((datetime.now(UTC) - stamp).total_seconds()))
            except ValueError:
                pass
        return {"text": output, "updated_seconds_ago": age}
