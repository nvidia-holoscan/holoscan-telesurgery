# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persist and supervise a node's simulation without delaying enrollment."""

import asyncio

from telesurgery_core.configuration import load, save
from telesurgery_sim.launch import Simulation
from telesurgery_sim.presets import PRESETS


class NodeSimulation:
    def __init__(self, node, *, persist=False):
        self.node = node
        self.path = node.local.directory / "environment.yaml" if persist else None
        self.environment = self.simulation = self.task = None
        self.error = ""

    @property
    def changing(self):
        return self.task is not None and not self.task.done()

    def select(self, environment, gui=False):
        if environment is not None and environment not in PRESETS:
            raise ValueError("Choose physical devices, MIRA or Franka")
        if self.changing:
            raise RuntimeError("The node is already changing environments")
        if self.node.local.workers:
            raise ValueError("Stop the node's streams before changing its environment")
        if gui and environment is None:
            raise ValueError("--sim-gui requires --sim")
        if self.path:
            save(self.path, {"environment": environment, "gui": gui})
        self.environment, self.error = environment, ""
        self.task = asyncio.create_task(self._switch(gui))

    async def _switch(self, gui):
        try:
            await self.node.disconnect()
            if self.simulation:
                await self.simulation.close()
                self.simulation = None
            local = self.node.local
            local.cameras.clear()
            local.robots.clear()
            local.seen_hsb.clear()
            local.simulation = None
            if self.environment:
                self.simulation = Simulation(
                    self.environment, local.directory / "simulation", gui=gui
                )
                local.simulation = await self.simulation.start()
        except (OSError, RuntimeError, ValueError) as exc:
            self.error = str(exc)

    def restore(self):
        if self.path and (saved := load(self.path)):
            self.select(saved["environment"], saved.get("gui", False))

    def status(self):
        if self.changing:
            status = {"status": "loading", "stage": "Changing environment"}
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
