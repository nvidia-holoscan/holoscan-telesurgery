# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay measured simulation endpoints through bounded, ordinary jog commands."""

import math

from telesurgery.controller.haply import CartesianHaply
from telesurgery.controller.replay import FeedbackPlayback


def validate_checkpoints(rows, *, environment="mira", device="keyboard"):
    """Validate the complete stream before joining a replay or acquiring control."""
    arms = {"left", "right"} if environment == "mira" else {"hand"}
    barrier = 0
    for row in rows:
        kinds = set(row) & {"pose", "tool_pose", "joint_pose", "grip", "hold_s", "barrier"}
        if len(kinds) != 1:
            raise ValueError("Each checkpoint requires one pose, grip, hold, or barrier")
        kind = kinds.pop()
        squeeze = row.get("squeeze", [])
        if (
            not isinstance(squeeze, list)
            or any(arm not in arms for arm in squeeze)
            or (squeeze and kind not in {"pose", "tool_pose", "hold_s"})
            or any(not closing_input(row, arm, device) for arm in squeeze)
        ):
            raise ValueError("Squeeze requires an explicitly held close key or button")
        value = row[kind]
        if kind == "barrier":
            if environment != "versius" or type(value) is not int or value != barrier + 1:
                raise ValueError("Handoff barriers must be consecutive, starting at one")
            barrier = value
            continue
        if kind == "hold_s":
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 30:
                raise ValueError("Invalid checkpoint hold duration")
            continue
        if kind == "joint_pose":
            if (
                environment != "versius"
                or not isinstance(value, list)
                or len(value) != 8
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
            ):
                raise ValueError("Joint preparation requires eight finite Versius angles")
            from telesurgery_robots.versius import LIMITS

            if any(not lo <= v <= hi for v, (lo, hi) in zip(value, LIMITS, strict=True)):
                raise ValueError("Joint checkpoint exceeds simulation limits")
        elif kind == "tool_pose":
            if environment not in {"franka", "versius"}:
                raise ValueError("Tool poses require Franka or Versius simulation")
            try:
                if value["frame"] != "base":
                    raise ValueError("Checkpoint tool poses must use the base frame")
                CartesianHaply.pose({"tool_pose": value})
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid checkpoint tool pose") from exc
        else:
            if kind == "pose" and environment != "mira":
                raise ValueError("XYZ/elbow/roll poses require MIRA simulation")
            if not isinstance(value, dict) or not value or set(value) - arms:
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


def closing_input(row, arm, device):
    if device == "keyboard":
        return ("n" if arm == "right" else "z") in row.get("keys", [])
    if device == "gamepad":
        return (14 if arm == "left" else 2) in row.get("buttons", [])
    # Haply grip buttons clutch tool motion; retain the closing load established
    # by its grip checkpoint, rather than inventing simultaneous pen movement.
    return False


class CheckpointPlayback(FeedbackPlayback):
    """Reach recorded poses before advancing, independent of packet count or RTT.

    MIRA records XYZ in millimetres and wrist angles in degrees. Franka and
    Versius record base-frame tool poses; Versius can also prepare a recorded
    joint configuration. Each correction uses the selected controller's normal
    bounds. Task sequencing stays on the surgeon, with ordinary stop/watchdog checks.
    """

    def __init__(self, robot, manifest, *args, **kwargs):
        super().__init__(robot, manifest, *args, **kwargs)
        self.environment = robot["kind"].removesuffix("-sim")
        validate_checkpoints(self.rows, environment=self.environment, device=self.mapping.device)
        self.synchronized = 0

    @property
    def checkpoint(self):
        """Last handoff barrier reached locally; never inferred from elapsed time."""
        return max((row.get("barrier", 0) for row in self.rows[: self.index + 1]), default=0)

    def tool_motion(self, state, goal):
        import numpy as np

        try:
            actual, rotation = CartesianHaply.pose(state)
            target, desired = CartesianHaply.pose({"tool_pose": goal})
            if state["tool_pose"].get("frame") != goal["frame"] or (
                state["tool_pose"].get("end_effector") != goal.get("end_effector")
            ):
                raise ValueError("Tool frame changed")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Replay requires valid measured tool pose feedback") from exc
        error = desired @ rotation.T
        angle = math.acos(float(np.clip((np.trace(error) - 1) / 2, -1, 1)))
        # Eigenvector fallback covers a valid 180-degree orientation difference.
        axis = np.array(
            [error[2, 1] - error[1, 2], error[0, 2] - error[2, 0], error[1, 0] - error[0, 1]]
        )
        if angle > math.pi - 1e-4:
            _, vectors = np.linalg.eigh((error + error.T) / 2)
            axis = vectors[:, -1]
        angular = axis * angle / max(1e-9, np.linalg.norm(axis))
        linear = target - actual
        distance = float(np.linalg.norm(linear))
        # The small Versius needle needs tighter arrival than the probe scan.
        position_tolerance = 0.0001 if self.environment == "versius" else 0.00025
        angle_tolerance = math.radians(0.15 if self.environment == "versius" else 0.3)
        reached = distance <= position_tolerance and angle <= angle_tolerance
        error_size = distance / position_tolerance + angle / angle_tolerance
        scale = self.mapping.inputs.speed / 20
        linear = linear * 2 / max(1e-9, 0.1 * scale)
        angular = angular * 2 / max(1e-9, math.radians(30) * scale)
        linear /= max(1, np.linalg.norm(linear))
        angular /= max(1, np.linalg.norm(angular))
        return (
            reached,
            error_size,
            ("jog", {"translation": linear.tolist(), "rotation": angular.tolist()}),
        )

    def progress(self, error, now):
        pending = self.pending
        initial = pending.setdefault("initial_error", error)
        if error < pending["best_error"] - 1:
            pending["best_error"] = error
            pending["deadline"] = now + 5
        return 1 - error / max(initial, 1e-9)

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
        if "barrier" in row:
            if self.synchronized < row["barrier"]:
                return {**result, "waiting_peer": True}
            self.index += 1
            return {**result, "done": self.finished}
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
        if state.get("stopping"):
            if state.get("stop_reason") not in {"released", "input expired"}:
                raise RuntimeError(state.get("stop_reason") or "Robot motion stopped")
            return {**result, "waiting_feedback": True}
        if not pending["acknowledged"]:
            return {**result, "waiting_feedback": True}
        if now < self.due_at:
            return result
        request = None
        reached = True
        fraction = 0.0
        if "pose" in row:
            # A target still in flight at observation can expire before the
            # next packet arrives. Near the endpoint, stop and observe again
            # so the final correction starts from a settled, measured pose.
            # MIRA's hold rebases the drive target to measured joints, so
            # arrival is measured before that release's static load deflection.
            near = all(
                abs(goal - actual) <= (0.2 if i < 3 else 0.3)
                for arm, goals in row["pose"].items()
                for i, (goal, actual) in enumerate(zip(goals, self.pose(state, arm), strict=True))
            )
            arrived = all(
                abs(goal - actual) <= (0.1 if i < 3 else 0.15)
                for arm, goals in row["pose"].items()
                for i, (goal, actual) in enumerate(zip(goals, self.pose(state, arm), strict=True))
            )
            if near and not arrived and state.get("control_active"):
                self.due_at = now + 0.05
                return {**result, "request": ("release", {}), "waiting_feedback": True}
            error = sum(
                abs(goal - actual) / (0.1 if i < 3 else 0.15)
                for arm, goals in row["pose"].items()
                for i, (goal, actual) in enumerate(zip(goals, self.pose(state, arm), strict=True))
            )
            fraction = self.progress(error, now)
            limits = inputs._tool(
                {arm: [inputs.increment(i, 0.05) for i in range(5)] for arm in inputs.groups}
            )
            command = {arm: [0.0] * count for arm, count in inputs.groups.items()}
            for arm, goals in row["pose"].items():
                actual = self.pose(state, arm)
                # A delayed packet may outlive the simulator's jog watchdog.
                # The next jog rebases on measured joints, so a held target is
                # no longer pending travel that should be subtracted twice.
                planned = (
                    actual
                    if state.get("control_active") is False
                    else self.pose(state, arm, planned=True)
                )
                for i, goal in enumerate(goals):
                    tolerance = 0.1 if i < 3 else 0.15
                    if abs(goal - actual[i]) > tolerance:
                        reached = False
                    remaining = goal - planned[i]
                    if abs(remaining) > 0.02:
                        command[arm][i] = max(-limits[arm][i], min(limits[arm][i], remaining))
            if not reached and any(v for values in command.values() for v in values):
                request = "cartesian", command
        elif "joint_pose" in row:
            # Use ordinary bounded joint steps and observe each completion.
            # Continuous joint jogs can expire during a long round trip and
            # leave the next packet racing the controller's braking phase.
            if pending.get("joint_issued"):
                if state.get("control_active"):
                    return {**result, "waiting_feedback": True}
                pending["joint_issued"] = False
            goal = row["joint_pose"]
            actual = state.get("joints_deg", {}).get("joints", [])
            planned = state.get("targets_deg", {}).get("joints", [])
            if any(
                len(v) != len(goal) or not all(math.isfinite(x) for x in v)
                for v in (actual, planned)
            ):
                raise ValueError("Replay requires measured and target joint feedback")
            errors = [abs(g - a) for g, a in zip(goal, actual, strict=True)]
            fraction = self.progress(sum(errors) / 0.1, now)
            reached = max(errors) <= 0.1
            if max(errors) <= 0.2 and state.get("control_active"):
                self.due_at = now + 0.05
                return {**result, "request": ("release", {}), "waiting_feedback": True}
            if not reached:
                command = [
                    max(-inputs.increment(i, 0.05), min(inputs.increment(i, 0.05), g - p))
                    for i, (g, p) in enumerate(zip(goal, planned, strict=True))
                ]
                if any(abs(v) > 0.001 for v in command):
                    request = "step", {"joints": command}
                    pending["joint_issued"] = True
        elif "tool_pose" in row:
            reached, error, request = self.tool_motion(state, row["tool_pose"])
            fraction = self.progress(error, now)
            if reached:
                # Stop the velocity controller and verify the settled pose before
                # advancing to a grasp, speed change, or handoff barrier.
                if type(state.get("control_active")) is not bool:
                    raise ValueError("Replay requires controller motion feedback")
                if state["control_active"]:
                    self.due_at = now + 0.05
                    return {**result, "request": ("release", {}), "waiting_feedback": True}
                request = None
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
            fraction = self.progress(error / 0.002, now)
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
