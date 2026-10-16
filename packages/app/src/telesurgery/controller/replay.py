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


def check_initial(state, initial, *, starting_scene="Home"):
    for group, expected in initial["joints_deg"].items():
        actual = state.get("joints_deg", {}).get(group, [])
        if len(actual) != len(expected) or any(
            abs(a - b) > 1.0 for a, b in zip(actual, expected, strict=True)
        ):
            raise ValueError(
                f"Starting joints differ ({group}); use {starting_scene} before replay"
            )
    for group, expected in initial.get("grippers", {}).items():
        if abs(state.get("grippers", {}).get(group, -1) - expected) > 0.04:
            raise ValueError(
                f"Starting gripper differs ({group}); use {starting_scene} before replay"
            )


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
            if manifest.get("version") not in {1, 2} or not manifest.get("replay_verified"):
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
        self.renewed = clock()
        self.input_row = None
        self.input_display = None

    def display_input(self, result):
        """Recorded controls for the dispatched step, never a wall-clock animation."""
        request = result.get("request")
        if result.get("done") or result.get("waiting_peer") or request and request[0] == "release":
            self.input_display = None
        elif request and self.input_row is not None:
            row = self.input_row
            self.input_display = {
                "device": self.mapping.device,
                "keys": list(row.get("keys", [])),
                "axes": list(row.get("axes", [0, 0, 0, 0])),
                "buttons": list(row.get("buttons", [])),
            }
        return self.input_display

    @property
    def finished(self):
        return self.index == len(self.rows)

    def read(self, elapsed, state):
        now = self.clock()
        if now - self.read_at > 0.3:
            raise TimeoutError("Replay paused because the dashboard stopped polling")
        self.read_at = now
        request = None
        if self.index < len(self.rows) and self.rows[self.index]["t"] <= elapsed:
            row = self.rows[self.index]
            self.input_row = row
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


class FeedbackPlayback(Playback):
    """Keep recorded cadence while tracking; pause at lag or input transitions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending = None
        self.previous_t = 0.0
        self.grip_goals = {}
        self.request = None
        self.due_at = None
        self.barrier = None
        self.polled_at = float("-inf")

    @property
    def finished(self):
        return super().finished and self.pending is None

    def acknowledge(self, state):
        self.request = None
        if self.pending is None:
            return
        self.pending["acknowledged"] = True
        if self.pending["mode"] != "grip":
            targets = state.get("targets_deg", {})
            if not all(group in targets for group in self.mapping.inputs.groups):
                raise ValueError("Replay requires controller target feedback")
            self.pending["targets"] = {
                group: list(targets[group][:count])
                for group, count in self.mapping.inputs.groups.items()
            }
            if any(
                len(values) != self.mapping.inputs.groups[group]
                or not all(math.isfinite(v) for v in values)
                for group, values in self.pending["targets"].items()
            ):
                raise ValueError("Replay requires valid controller target feedback")

    def validate_request(self, mode, command):
        expected = self.request
        if (
            not expected
            or mode != expected[0]
            or command != ({"velocity": expected[1]} if mode == "grip" else expected[1])
        ):
            raise RuntimeError("Replay input is no longer current")
        now = self.clock()
        if now - self.read_at > 0.3:
            raise TimeoutError("Replay paused because the dashboard stopped polling")
        if not self.pending or now > self.pending["deadline"]:
            raise TimeoutError("Replay stopped: measured motion did not reach its target")

    def read(self, elapsed, state):
        now = self.clock()
        if now - self.read_at > 0.3:
            raise TimeoutError("Replay paused because the dashboard stopped polling")
        self.read_at = now
        result = {
            "request": None,
            "speed_deg_s": self.mapping.inputs.speed,
            "done": self.finished,
            "elapsed": self.previous_t,
            "waiting_feedback": False,
        }
        if self.pending:
            pending = self.pending
            if now > pending["deadline"]:
                raise TimeoutError("Replay stopped: measured motion did not reach its target")
            if not pending.get("acknowledged"):
                return {**result, "waiting_feedback": True}
            if pending["mode"] == "grip":
                positions = state.get("grippers", {})
                rates = {}
                for group, goal in pending["goals"].items():
                    actual = positions.get(group)
                    if actual is None or not math.isfinite(actual):
                        raise ValueError("Replay requires measured gripper feedback")
                    rate = pending["rates"][group]
                    previous, progressed = pending["progress"][group]
                    if abs(actual - previous) > 0.001:
                        pending["progress"][group] = actual, now
                        progressed = now
                    # Closing on an object need not reach the empty-jaw pose.
                    # After the recorded squeeze duration, a stationary jaw
                    # can release the input while the controller retains its
                    # bounded closing load. This does not verify a grasp.
                    contact = (
                        rate < 0 and now >= pending["squeeze_until"] and now - progressed >= 0.3
                    )
                    if not contact and (goal - actual) * math.copysign(1, rate) > 0.002:
                        rates[group] = rate
                result["request"] = ("grip", rates) if rates else ("release", {})
                if rates:
                    self.request = result["request"]
                    return {**result, "waiting_feedback": True}
                self.pending = None
                self.due_at = now
                result["done"] = self.finished
                return result
            # Continuous input already runs inside the controller's bounded
            # tracking envelope. Settling every 50 ms sample makes normal
            # servo lag accumulate into a slow, stop/start replay. Require
            # settling at key/speed transitions, including the final release.
            continuing = self.index < len(self.rows) and all(
                self.rows[self.index][field] == self.rows[self.index - 1][field]
                for field in ("keys", "speeds")
            )
            tolerance = 1.0 if continuing else 0.35
            for group, goal in pending["targets"].items():
                actual = state.get("joints_deg", {}).get(group, [])
                if len(actual) != len(goal) or not all(math.isfinite(v) for v in actual):
                    raise ValueError("Replay requires measured joint feedback")
                if any(abs(a - b) > tolerance for a, b in zip(actual, goal, strict=True)):
                    self.due_at = max(self.due_at or now, now)
                    return {**result, "waiting_feedback": True}
            self.pending = None
        if self.finished:
            return {**result, "done": True}
        row = self.rows[self.index]
        if elapsed < 0:
            return result
        if self.due_at is None:
            self.due_at = now - elapsed + row["t"]
        if now < self.due_at:
            return result
        # Preserve cadence through small scheduler jitter, but never emit a
        # burst to catch up after a delayed link or a stalled robot.
        self.due_at = max(self.due_at, now - 0.01)
        self.input_row = row
        request = self.mapping.update(row, state, row["t"])
        self.index += 1
        self.previous_t = row["t"]
        if request and request[0] != "release":
            mode, command = request
            self.pending = {"mode": mode, "deadline": now + 5.0}
            if mode == "grip":
                # Identical grip-only samples describe one held key. Convert its
                # recorded duration to a position goal; network time must not
                # extend the grip. Never skip a key or speed transition.
                end = self.index
                if set(row["keys"]) <= {"z", "x", "n", "m"}:
                    while end < len(self.rows) and all(
                        self.rows[end][field] == row[field] for field in ("keys", "speeds")
                    ):
                        end += 1
                until = (
                    self.rows[end]["t"] if end < len(self.rows) else self.rows[end - 1]["t"] + 0.05
                )
                duration = until - row["t"]
                rates = {group: rate for group, rate in command.items() if rate}
                positions = state.get("grippers", {})
                if any(
                    group not in positions or not math.isfinite(positions[group]) for group in rates
                ):
                    raise ValueError("Replay requires measured gripper feedback")
                goals = {
                    group: max(
                        0, min(1, self.grip_goals.get(group, positions[group]) + rate * duration)
                    )
                    for group, rate in rates.items()
                }
                self.grip_goals.update(goals)
                self.pending.update(
                    rates=rates,
                    goals=goals,
                    progress={group: (positions[group], now) for group in rates},
                    squeeze_until=now + duration,
                    deadline=now + max(5.0, duration * 4 + 2),
                )
                if end > self.index:
                    self.mapping.update(self.rows[end - 1], state, self.rows[end - 1]["t"])
                self.index = end
                self.previous_t = until
        if self.index < len(self.rows):
            self.due_at += self.rows[self.index]["t"] - row["t"]
        self.request = request
        return {**result, "request": request, "done": self.finished, "elapsed": self.previous_t}


class Rendezvous:
    """Track owned simulation replays, with optional shared checkpoints."""

    def __init__(self, catalog, clock=time.monotonic):
        self.catalog, self.clock = catalog, clock
        self.runs = {}

    def join(self, recording, robot, peer, token):
        path, manifest, role = self.catalog.get(recording, robot)
        node = robot["id"].split(":", 1)[0]
        # Device recordings of one checkpoint task share the same handoff.
        # Legacy timed streams still require their exact recording and clock.
        group = manifest.get("handoff_group", recording) if manifest["version"] == 2 else recording
        key = node, manifest["environment"], manifest["version"], group
        solo = manifest.get("independent_actions") is True
        if solo:
            if manifest["version"] != 2 or manifest["environment"] != "versius":
                raise ValueError("Independent handoff actions require Versius checkpoints")
            key += (role,)
        roles = {role} if solo else set(manifest["streams"])
        run = self.runs.get(key)
        now = self.clock()
        if run and (
            (
                set(run["members"]) == run["roles"]
                and all(m.get("done") for m in run["members"].values())
            )
            or any(now - member["seen"] > 0.5 for member in run["members"].values())
        ):
            del self.runs[key]
            run = None
        if run and run["started"] is not None and not run["independent"]:
            raise RuntimeError("Stop the previous replay before preparing another")
        if run and (run["roles"] != roles or run["barriers"] != manifest.get("barriers", 0)):
            raise ValueError("Recordings have incompatible handoff checkpoints")
        if run is None:
            run = {
                "id": secrets.token_urlsafe(16),
                "members": {},
                "started": None,
                "barriers": manifest.get("barriers", 0),
                "roles": roles,
                "independent": manifest["version"] == 2,
                "solo": solo,
            }
            self.runs[key] = run
        if role in run["members"]:
            raise RuntimeError("This arm is already ready for replay")
        if manifest["environment"] == "versius" and any(
            member["peer"] == peer for member in run["members"].values()
        ):
            raise PermissionError("Use a separate surgeon for each Versius arm")
        run["members"][role] = {"peer": peer, "token": token, "key": robot["id"], "seen": now}
        if solo and manifest.get("requires_presented_needle") is True:
            rows = read_rows(path.parent / manifest["streams"][role]["file"])
            pose = None
            for row in rows:
                if "handoff" in row:
                    break
                pose = row.get("tool_pose", pose)
            run["handoff"] = {
                **run["members"][role],
                "role": role,
                "pose": pose,
                "run": run["id"],
                "group": group,
            }
        # Feedback-paced streams can begin independently. A surgeon joining
        # later shares the existing handoff barriers, without restarting it.
        if run["independent"] and run["started"] is None:
            run["started"] = now
        elif not run["independent"] and set(run["members"]) == run["roles"]:
            run["started"] = now + 1.0
        return run["id"]

    def handoff(self, run_id):
        """Replay-only release consent; callers must first validate with poll()."""
        return next((run.get("handoff") for run in self.runs.values() if run["id"] == run_id), None)

    def poll(self, run_id, peer, key, owners, *, finished=False, checkpoint=None):
        found = next(((k, v) for k, v in self.runs.items() if v["id"] == run_id), None)
        if found is None:
            raise RuntimeError("Replay stopped")
        identity, run = found
        member = next((m for m in run["members"].values() if m["key"] == key), None)
        if member is None or member["peer"] != peer:
            raise PermissionError("This replay belongs to another surgeon")
        now = self.clock()
        member["seen"] = now
        if checkpoint is not None:
            if (
                type(checkpoint) is not int
                or not member.get("checkpoint", 0) <= checkpoint <= run["barriers"]
            ):
                raise ValueError("Invalid replay handoff checkpoint")
            member["checkpoint"] = checkpoint
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
        joined = set(run["members"]) == run["roles"]
        return {
            "independent_actions": run["solo"],
            "handoff_required": bool(run.get("handoff")),
            "checkpoint": min(m.get("checkpoint", 0) for m in run["members"].values())
            if joined and run["started"] is not None
            else 0,
            "elapsed": None if run["started"] is None else now - run["started"],
            "done": joined
            and run["started"] is not None
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
