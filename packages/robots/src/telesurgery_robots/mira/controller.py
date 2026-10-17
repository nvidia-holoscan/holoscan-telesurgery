# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Owned lifecycle of the vendor MIRA daemon on its device node."""

import asyncio
import hashlib
import ipaddress
import json
import os
import secrets
import time
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
        suffix = "-sdk4" if os.environ.get("TELESURGERY_SDK") == "4" else ""
        self.image = spec["controller"].get(
            "image",
            f"holoscan-telesurgery:{version('telesurgery-robots')}{suffix}",
        )
        self.identity = hashlib.sha256(f"{self.directory}:{spec['id']}".encode()).hexdigest()[:12]
        self.name = f"telesurgery-mira-{self.identity}"
        self.session = secrets.token_hex(16)
        self.owned = False
        self.stop_pending = False
        self.lease_task = None
        self.lease_path = self.directory / f"controller-{self.identity}" / f"lease-{self.session}"

    async def _heartbeat(self):
        while True:
            temporary = self.lease_path.with_suffix(".tmp")
            temporary.write_text(str(time.monotonic()))
            temporary.replace(self.lease_path)
            await asyncio.sleep(0.5)

    def _ours(self, info):
        return info["Config"].get("Labels", {}).get(self.label + ".session") == self.session

    async def _docker(self, *args):
        process = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT if args[0] == "logs" else asyncio.subprocess.PIPE,
        )
        try:
            output, error = await asyncio.wait_for(
                process.communicate(), 8 if args[0] in {"run", "stop"} else 2
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
            if self.stop_pending:
                return {
                    "status": "error",
                    "error": "MIRA API stop is unconfirmed; retry cleanup before startup.",
                }
            if running and not self._ours(info):
                return {
                    "status": "error",
                    "error": (
                        "MIRA API is already running from another node session. "
                        "Stop its owner before connecting this node."
                    ),
                }
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
            "--label",
            f"{self.label}.session={self.session}",
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
            "python",
            self.image,
            "-m",
            "telesurgery_robots.mira.supervisor",
            f"/work/{self.lease_path.name}",
            "/opt/mira-api",
        ]

    async def start(self):
        if self.stop_pending:
            await self.stop()
        info = await self._inspect()
        if info and info["State"].get("Running"):
            if not self._ours(info) or not self.owned:
                raise RuntimeError(
                    "MIRA API is already running from another node session. "
                    "Stop its owner before connecting this node."
                )
            return  # Repeated clicks or a node reconnect never restart an active controller.
        command = self.command()
        # Only an existing local image is used; do not download during robot startup.
        await self._docker("image", "inspect", self.image)
        if info:
            await self._docker("rm", self.name)
        if self.lease_task:
            self.lease_task.cancel()
            await asyncio.gather(self.lease_task, return_exceptions=True)
        self.lease_task = asyncio.create_task(self._heartbeat())
        await asyncio.sleep(0)  # Publish the lease before starting the supervisor.
        try:
            await self._docker(*command)
            self.owned = True
        except BaseException:
            self.lease_task.cancel()
            await asyncio.gather(self.lease_task, return_exceptions=True)
            self.lease_task = None
            self.lease_path.unlink(missing_ok=True)
            raise

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

    async def stop(self):
        try:
            if self.owned:
                self.stop_pending = True
                info = await self._inspect()
                if info and info["State"].get("Running"):
                    if not self._ours(info):
                        raise RuntimeError("Controller belongs to another node session")
                    await self._docker("stop", "--time", "5", info["Id"])
            self.owned = False
            self.stop_pending = False
        finally:
            # A failed Docker operation must still end the supervisor lease.
            # Keep ownership until cleanup succeeds so the next call can retry.
            if self.lease_task:
                self.lease_task.cancel()
                await asyncio.gather(self.lease_task, return_exceptions=True)
                self.lease_task = None
            self.lease_path.unlink(missing_ok=True)
