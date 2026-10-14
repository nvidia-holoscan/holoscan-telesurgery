# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay measured MIRA keyboard endpoints through bounded, ordinary jog commands."""

import math

from telesurgery.controller.replay import FeedbackPlayback


def validate_checkpoints(rows):
    for row in rows:
        kinds = set(row) & {"pose", "grip", "hold_s"}
        if len(kinds) != 1:
            raise ValueError("Each checkpoint requires one pose, grip, or hold")
        kind = kinds.pop()
        squeeze = row.get("squeeze", [])
        if (
            not isinstance(squeeze, list)
            or set(squeeze) - {"left", "right"}
            or (squeeze and kind == "grip")
            or any(("z" if arm == "left" else "n") not in row["keys"] for arm in squeeze)
        ):
            raise ValueError("Squeeze requires an explicitly held close key")
        value = row[kind]
        if kind == "hold_s":
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 30:
                raise ValueError("Invalid checkpoint hold duration")
            continue
        if not isinstance(value, dict) or not value or set(value) - {"left", "right"}:
            raise ValueError("Invalid checkpoint arms")
        for target in value.values():
            values = target if kind == "pose" else [target]
            if not isinstance(values, list) or (kind == "pose" and len(values) != 5):
                raise ValueError("Checkpoint poses require XYZ, elbow, and roll")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError("Checkpoint targets must be finite")
            if kind == "grip" and not 0 <= target <= 1:
                raise ValueError("Invalid checkpoint gripper position")
        if any(speed <= 0 for speed in row["speeds"]):
            raise ValueError("Checkpoint motion requires positive speeds")


class CheckpointPlayback(FeedbackPlayback):
    """Reach recorded poses before advancing, independent of packet count or RTT.

    Pose checkpoints contain XYZ in millimetres, elbow and roll in degrees.
    Speeds use the keyboard mapping's existing per-command bounds. No task
    motion runs on the patient, and ordinary stop/watchdog checks still apply.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        validate_checkpoints(self.rows)

    def acknowledge(self, state):
        self.request = None
        if self.pending:
            self.pending["acknowledged"] = True

    @staticmethod
    def pose(state, arm, *, planned=False):
        field = "cartesian_target_mm_deg" if planned else "cartesian_mm_deg"
        try:
            values = list(state[field][arm]) + [state["joints_deg"][arm][4]]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Replay requires measured and target MIRA pose feedback") from exc
        if len(values) != 5 or not all(math.isfinite(v) for v in values):
            raise ValueError("Replay requires valid MIRA pose feedback")
        return values

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
        if self.finished or elapsed < 0:
            return result
        row = self.rows[self.index]
        inputs = self.mapping.inputs
        inputs.arm_percent, inputs.roll_percent, inputs.grip_percent = row["speeds"]
        result["speed_deg_s"] = inputs.speed
        limits = inputs._tool(
            {arm: [inputs.increment(i, 0.05) for i in range(5)] for arm in inputs.groups}
        )
        if self.pending is None:
            duration = row.get("hold_s", 0)
            self.pending = {
                "mode": "grip" if "grip" in row else "cartesian",
                "deadline": now + (duration + 5 if "hold_s" in row else 8),
                "best_error": float("inf"),
                "started": now,
                "acknowledged": True,
                "progress": {},
            }
            self.due_at = now
        pending = self.pending
        if now > pending["deadline"]:
            raise TimeoutError("Replay stopped: measured motion did not reach its checkpoint")
        if not pending["acknowledged"]:
            return {**result, "waiting_feedback": True}
        if now < self.due_at:
            return result
        request = None
        reached = True
        fraction = 0.0
        if "pose" in row:
            error = sum(
                abs(goal - actual) / (0.1 if i < 3 else 0.15)
                for arm, goals in row["pose"].items()
                for i, (goal, actual) in enumerate(zip(goals, self.pose(state, arm), strict=True))
            )
            initial_error = pending.setdefault("initial_error", error)
            fraction = 1 - error / max(initial_error, 1e-9)
            if error < pending["best_error"] - 1:
                pending["best_error"] = error
                pending["deadline"] = now + 5
            command = {arm: [0.0] * count for arm, count in inputs.groups.items()}
            for arm, goals in row["pose"].items():
                actual, planned = self.pose(state, arm), self.pose(state, arm, planned=True)
                for i, goal in enumerate(goals):
                    tolerance = 0.1 if i < 3 else 0.15
                    if abs(goal - actual[i]) > tolerance:
                        reached = False
                    remaining = goal - planned[i]
                    if abs(remaining) > 0.02:
                        command[arm][i] = max(-limits[arm][i], min(limits[arm][i], remaining))
            if not reached and any(v for values in command.values() for v in values):
                request = "cartesian", command
        elif "grip" in row:
            rates = {}
            error = 0.0
            for arm, goal in row["grip"].items():
                actual = state.get("grippers", {}).get(arm)
                if actual is None or not math.isfinite(actual):
                    raise ValueError("Replay requires measured gripper feedback")
                error += abs(goal - actual)
                previous, progressed = pending["progress"].setdefault(arm, (actual, now))
                if abs(actual - previous) > 0.001:
                    pending["progress"][arm] = actual, now
                    progressed = now
                contact = goal == 0 and now - pending["started"] >= 1.2 and now - progressed >= 0.3
                if abs(goal - actual) > 0.002 and not contact:
                    reached = False
                    rate = (
                        inputs.grip_speed
                        if goal == 0
                        else min(inputs.grip_speed, abs(goal - actual) / 0.15)
                    )
                    rates[arm] = math.copysign(rate, goal - actual)
            initial_error = pending.setdefault("initial_error", error)
            fraction = 1 - error / max(initial_error, 1e-9)
            if rates:
                request = "grip", rates
        else:
            reached = now - pending["started"] >= row["hold_s"]
            fraction = (now - pending["started"]) / max(row["hold_s"], 1e-9)
        until = (
            self.rows[self.index + 1]["t"]
            if self.index + 1 < len(self.rows)
            else row["t"] + row.get("hold_s", 0)
        )
        self.previous_t = max(
            self.previous_t, row["t"] + (until - row["t"]) * max(0, min(1, fraction))
        )
        result["elapsed"] = self.previous_t
        if reached:
            self.pending = None
            self.index += 1
            self.previous_t = until
            self.request = None
            return {
                **result,
                "request": ("release", {}),
                "done": self.finished,
                "elapsed": self.previous_t,
            }
        if row.get("squeeze") and (pending.get("last_mode") != "grip" or request is None):
            request = "grip", {arm: -inputs.grip_speed for arm in row["squeeze"]}
        if request:
            pending["last_mode"] = request[0]
            self.request = request
            pending["acknowledged"] = False
            self.due_at = now + 0.05
        return {
            **result,
            "request": request,
            "waiting_feedback": request is None and "hold_s" not in row,
        }
