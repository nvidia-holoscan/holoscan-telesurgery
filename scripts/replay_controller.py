# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay recorded device inputs through approved surgeon dashboards (simulation only)."""

import argparse
import asyncio
import contextlib
import json
import time
from pathlib import Path

import aiohttp
from telesurgery.controller.checkpoint_replay import CheckpointPlayback, validate_checkpoints
from telesurgery.controller.replay import InputMapping, check_initial, read_rows


class Surgeon:
    def __init__(self, http, url, robot_id):
        self.http, self.url, self.robot_id = http, url.rstrip("/"), robot_id
        self.state = {}
        self.acquired = False
        self.lock = asyncio.Lock()

    async def inventory(self, environment):
        async with self.http.get(self.url + "/api/status") as response:
            response.raise_for_status()
            status = await response.json()
        if status.get("role") != "surgeon":
            raise ValueError("Bind a surgeon dashboard, not a patient dashboard")
        robot = next(
            (r for r in status.get("session", {}).get("robots", []) if r["id"] == self.robot_id),
            None,
        )
        if not robot or robot.get("kind") != environment + "-sim":
            raise ValueError(f"{self.robot_id}: replay requires the matching simulation robot")
        if robot.get("owner_id"):
            raise ValueError(f"{self.robot_id}: release existing control before replay")
        return robot

    async def action(self, action, **params):
        async with self.lock:
            async with self.http.post(
                self.url + "/api/action",
                json={"action": action, "params": {"id": self.robot_id, **params}},
            ) as response:
                body = await response.json()
                if response.status >= 400:
                    raise RuntimeError(body.get("error", f"HTTP {response.status}"))
            result = body["result"]
            if isinstance(result, dict):
                self.state = result
            return result

    async def acquire(self, initial, *, starting_scene="Home"):
        await self.action("robot.acquire")
        self.acquired = True
        try:
            check_initial(self.state, initial, starting_scene=starting_scene)
        except ValueError as exc:
            raise ValueError(f"{self.robot_id}: {exc}") from exc

    async def send(self, request, inputs):
        if request is None:
            await self.action("robot.renew")
            return
        mode, command = request
        if mode == "release":
            await self.action("robot.hold")
        else:
            await self.action(
                "robot.move",
                mode=mode,
                command={"velocity": command} if mode == "grip" else command,
                **({"speed_deg_s": inputs.speed} if inputs.controls.get("speed_deg_s") else {}),
            )

    async def renew(self):
        while True:
            await asyncio.sleep(0.5)
            await self.action("robot.renew")

    async def release(self):
        if self.acquired:
            # Attempt both even when the transport fails during Stop.
            try:
                await self.action("robot.hold")
            finally:
                await self.action("robot.release")
                self.acquired = False


async def deadline(start, timestamp):
    delay = start + timestamp - time.monotonic()
    if delay < -0.15:
        raise TimeoutError(
            "Replay fell behind by more than 150 ms; stopping instead of queuing input"
        )
    await asyncio.sleep(max(0, delay))


async def play(surgeon, robot, rows, device, environment, start):
    mapping = InputMapping(robot, device)
    inputs = mapping.inputs
    for row in rows:
        await deadline(start, row["t"])
        request = mapping.update(row, surgeon.state, row["t"])
        await surgeon.send(request, inputs)
        if surgeon.state.get("stopping") and surgeon.state.get("stop_reason") != "released":
            raise RuntimeError(surgeon.state.get("stop_reason", "Robot stopped"))


async def play_checkpoints(surgeon, robot, rows, start):
    await asyncio.sleep(max(0, start - time.monotonic()))
    playback = CheckpointPlayback(robot, {"device": "keyboard"}, "mira", rows, "cli")
    while True:
        result = playback.read(time.monotonic() - start, surgeon.state)
        try:
            await surgeon.send(result["request"], playback.mapping.inputs)
        except RuntimeError as exc:
            if not result["request"] or str(exc) != "Robot input expired in transit":
                raise
            # Admission rejection confirms no motion was dispatched. Refresh
            # feedback and recompute; an unknown command outcome still fails.
            await surgeon.action("robot.renew")
            playback.read_at = time.monotonic()
        if result["request"]:
            playback.acknowledge(surgeon.state)
        if result["done"]:
            return
        await asyncio.sleep(0.01)


async def run(manifest_path, bindings):
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") not in {1, 2} or manifest.get("environment") not in {
        "mira",
        "franka",
        "versius",
    }:
        raise ValueError("Unsupported replay format or simulation")
    device, environment = manifest["device"], manifest["environment"]
    if device not in {"keyboard", "gamepad", "haply"}:
        raise ValueError("Unknown input device")
    checkpoint = manifest["version"] == 2
    if checkpoint and (environment, device) != ("mira", "keyboard"):
        raise ValueError("Pose checkpoints require MIRA simulation keyboard inputs")
    roles = manifest["streams"]
    if len(bindings) != len(roles) or {b[0] for b in bindings} != set(roles):
        raise ValueError(f"Bind each recorded stream exactly once: {', '.join(roles)}")
    if environment == "versius" and len({b[1].rstrip("/") for b in bindings}) != len(roles):
        raise ValueError("Use a separate surgeon dashboard for each Versius stream")
    # Read and validate all files and robot identities before acquiring anything.
    rows = {role: read_rows(manifest_path.parent / spec["file"]) for role, spec in roles.items()}
    if checkpoint:
        for stream_rows in rows.values():
            validate_checkpoints(stream_rows)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as http:
        surgeons = {role: Surgeon(http, url, robot) for role, url, robot in bindings}
        inventory = {
            role: await surgeon.inventory(environment) for role, surgeon in surgeons.items()
        }
        try:
            for role, surgeon in surgeons.items():
                await surgeon.acquire(
                    roles[role]["initial"], starting_scene=manifest.get("starting_scene", "Home")
                )
            start = time.monotonic() + 1
            print(f"Replaying {environment}/{device}: {manifest['task']}", flush=True)
            async with asyncio.TaskGroup() as group:

                async def stream(role, surgeon):
                    renew = asyncio.create_task(surgeon.renew())
                    motion = asyncio.create_task(
                        play_checkpoints(surgeon, inventory[role], rows[role], start)
                        if checkpoint
                        else play(surgeon, inventory[role], rows[role], device, environment, start)
                    )
                    try:
                        done, _ = await asyncio.wait(
                            (renew, motion), return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in done:
                            await task
                    finally:
                        renew.cancel()
                        motion.cancel()
                        await asyncio.gather(renew, motion, return_exceptions=True)
                    await surgeon.release()

                for role, surgeon in surgeons.items():
                    group.create_task(stream(role, surgeon))
        finally:
            for surgeon in surgeons.values():
                try:
                    await surgeon.release()
                except Exception as error:
                    print(f"Could not confirm release of {surgeon.robot_id}: {error}", flush=True)
    print("Replay finished; control released.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--bind",
        nargs=3,
        action="append",
        required=True,
        metavar=("STREAM", "SURGEON_URL", "ROBOT_ID"),
    )
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args.manifest, args.bind))


if __name__ == "__main__":
    main()
