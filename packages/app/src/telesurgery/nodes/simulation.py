# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Supervise one node's simulation while reporting startup progress."""

import asyncio

from telesurgery_sim.environments.presets import PRESETS
from telesurgery_sim.runtime.launch import Simulation


class NodeSimulation:
    def __init__(self, node):
        self.node = node
        self.environment = self.simulation = self.task = None
        self.error = ""

    @property
    def changing(self):
        return self.task is not None and not self.task.done()

    def start(self, environment, gui=False):
        if environment not in PRESETS:
            raise ValueError("Choose MIRA or Franka")
        self.environment = environment
        self.task = asyncio.create_task(self._start(gui))

    async def _start(self, gui):
        try:
            self.simulation = Simulation(
                self.environment, self.node.local.directory / "simulation", gui=gui
            )
            self.node.local.simulation = await self.simulation.start()
        except (OSError, RuntimeError, ValueError) as exc:
            self.error = str(exc)

    def status(self):
        if self.changing:
            status = {"status": "loading", "stage": "Starting simulation"}
        elif self.error:
            status = {"status": "error", "error": self.error}
        else:
            status = self.simulation.status() if self.simulation else None
        return {"environment": self.environment, "simulation": status}

    async def log(self):
        if self.simulation:
            return await asyncio.to_thread(self.simulation.log)
        return {"text": self.error, "updated_seconds_ago": None}

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.simulation:
            await self.simulation.close()
