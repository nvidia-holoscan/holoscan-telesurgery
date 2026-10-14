# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Recorded device input for owned simulation robots; motion stays on the usual path."""

import gzip
import json
import math
import secrets
import time
from pathlib import Path

from telesurgery.controller.haply import CartesianHaply, MiraHaply, Sample
from telesurgery.controller.input import Inputs

ROOT = Path(__file__).resolve().parents[5] / "examples/controller-replays"


def read_rows(path):
    with gzip.open(path, "rt") as source:
        rows = [json.loads(line) for line in source]
    previous = -1.0
    for row in rows:
        timestamp = row["t"]
        if not math.isfinite(timestamp) or timestamp < 0 or timestamp < previous:
            raise ValueError(f"Invalid input timestamps in {path}")
        if len(row["speeds"]) != 3 or any(
            not math.isfinite(v) or not 0 <= v <= 100 for v in row["speeds"]
        ):
            raise ValueError(f"Invalid input speeds in {path}")
        previous = timestamp
    if not rows:
        raise ValueError(f"Empty input stream: {path}")
    return rows


def check_initial(state, initial):
    for group, expected in initial["joints_deg"].items():
        actual = state.get("joints_deg", {}).get(group, [])
        if len(actual) != len(expected) or any(
            abs(a - b) > 1.0 for a, b in zip(actual, expected, strict=True)
        ):
            raise ValueError("Starting joints differ; restore Home before replay")
    for group, expected in initial.get("grippers", {}).items():
        if abs(state.get("grippers", {}).get(group, -1) - expected) > 0.04:
            raise ValueError("Starting gripper differs; restore Home before replay")


class InputMapping:
    def __init__(self, robot, device):
        self.inputs = Inputs(robot)
        self.device = device
        mira = robot["kind"] == "mira-sim"
        if mira:
            self.inputs.mode = "mira-tool"
        self.mapper = (MiraHaply() if mira else CartesianHaply()) if device == "haply" else None

    def update(self, row, state, now):
        inputs = self.inputs
        inputs.arm_percent, inputs.roll_percent, inputs.grip_percent = row["speeds"]
        if self.device == "keyboard":
            keys = set(row["keys"])
            for key in inputs.keyboard.down - keys:
                inputs.keyboard.release(key, now)
            inputs.keyboard.poll(now + 0.021)
            for key in keys:
                inputs.keyboard.press(key, now)
            return inputs.from_keyboard(now)
        if self.device == "gamepad":
            return inputs.from_gamepad(row["axes"], set(row["buttons"]), state, now)
        sample = row["sample"]
        request = self.mapper.update(
            Sample(
                ("recorded-inverse3", "recorded-versegrip"),
                tuple(sample["position"]),
                tuple(sample["orientation"]),
                frozenset(sample["buttons"]),
                now,
                1,
            ),
            state,
            inputs,
            now,
        )
        if self.mapper.error:
            raise RuntimeError(self.mapper.error)
        return request


class Catalog:
    def __init__(self, root=ROOT):
        self.recordings = {}
        for path in root.glob("*/*/manifest.json"):
            manifest = json.loads(path.read_text())
            if manifest.get("version") != 1 or not manifest.get("replay_verified"):
                continue
            if manifest.get("environment") not in {"mira", "franka", "versius"}:
                continue
            if manifest.get("device") not in {"keyboard", "gamepad", "haply"}:
                continue
            if not all((path.parent / s["file"]).is_file() for s in manifest["streams"].values()):
                continue
            key = str(path.parent.relative_to(root))
            self.recordings[key] = path, manifest

    def list(self):
        return [
            {
                "id": key,
                "environment": manifest["environment"],
                "device": manifest["device"],
                "task": manifest["task"],
                "streams": list(manifest["streams"]),
            }
            for key, (_, manifest) in sorted(self.recordings.items())
        ]

    def get(self, key, robot):
        if key not in self.recordings:
            raise ValueError("No verified replay is available")
        path, manifest = self.recordings[key]
        if not robot.get("simulation") or robot.get("kind") != manifest["environment"] + "-sim":
            raise ValueError("Replay requires the matching simulation robot")
        role = robot["id"].split(":", 1)[-1]
        if role not in manifest["streams"]:
            raise ValueError("No replay is available for this arm")
        return path, manifest, role


class Playback:
    def __init__(self, robot, manifest, role, rows, run, clock=time.monotonic):
        self.mapping = InputMapping(robot, manifest["device"])
        self.rows, self.run = rows, run
        self.index = 0
        self.clock = clock
        self.read_at = clock()
        self.role = role

    def read(self, elapsed, state):
        now = self.clock()
        if now - self.read_at > 0.3:
            raise TimeoutError("Replay paused because the dashboard stopped polling")
        self.read_at = now
        request = None
        if self.index < len(self.rows) and self.rows[self.index]["t"] <= elapsed:
            row = self.rows[self.index]
            if elapsed - row["t"] > 0.15:
                raise TimeoutError("Replay fell behind; stopped without queuing input")
            # Use the recorded sampling clock for button edges and mapper rate limits.
            request = self.mapping.update(row, state, row["t"])
            self.index += 1
        return {
            "request": request,
            "speed_deg_s": self.mapping.inputs.speed,
            "done": self.index == len(self.rows),
            "elapsed": max(0, elapsed),
        }


class Rendezvous:
    """Patient-side start barrier. Each surgeon can prepare only its own arm."""

    def __init__(self, catalog, clock=time.monotonic):
        self.catalog, self.clock = catalog, clock
        self.runs = {}

    def join(self, recording, robot, peer, token):
        _, manifest, role = self.catalog.get(recording, robot)
        node = robot["id"].split(":", 1)[0]
        key = node, recording
        run = self.runs.get(key)
        now = self.clock()
        if run and (
            all(m.get("done") for m in run["members"].values())
            or any(now - member["seen"] > 0.5 for member in run["members"].values())
        ):
            del self.runs[key]
            run = None
        if run and run["started"] is not None:
            raise RuntimeError("Stop the previous replay before preparing another")
        if run is None:
            run = {"id": secrets.token_urlsafe(16), "members": {}, "started": None}
            self.runs[key] = run
        if role in run["members"]:
            raise RuntimeError("This arm is already ready for replay")
        if manifest["environment"] == "versius" and any(
            member["peer"] == peer for member in run["members"].values()
        ):
            raise PermissionError("Use a separate surgeon for each Versius arm")
        run["members"][role] = {"peer": peer, "token": token, "key": robot["id"], "seen": now}
        if set(run["members"]) == set(manifest["streams"]):
            run["started"] = now + 1.0
        return run["id"]

    def poll(self, run_id, peer, key, owners, *, finished=False):
        found = next(((k, v) for k, v in self.runs.items() if v["id"] == run_id), None)
        if found is None:
            raise RuntimeError("Replay stopped")
        identity, run = found
        member = next((m for m in run["members"].values() if m["key"] == key), None)
        if member is None or member["peer"] != peer:
            raise PermissionError("This replay belongs to another surgeon")
        now = self.clock()
        member["seen"] = now
        member["done"] = finished
        for item in run["members"].values():
            owner = owners.get(item["key"])
            if (
                owner is None
                or owner.owner != item["peer"]
                or owner.token != item["token"]
                or owner.expired()
                or now - item["seen"] > 0.5
            ):
                del self.runs[identity]
                raise RuntimeError(
                    "Replay stopped because a participant lost control or disconnected"
                )
        return {
            "elapsed": None if run["started"] is None else now - run["started"],
            "done": run["started"] is not None
            and all(m.get("done") for m in run["members"].values()),
        }

    def cancel(self, run_id, peer, key):
        for identity, run in list(self.runs.items()):
            if run["id"] == run_id:
                if not any(m["peer"] == peer and m["key"] == key for m in run["members"].values()):
                    raise PermissionError("This replay belongs to another surgeon")
                del self.runs[identity]

    def released(self, key):
        for identity, run in list(self.runs.items()):
            if any(member["key"] == key for member in run["members"].values()):
                del self.runs[identity]
