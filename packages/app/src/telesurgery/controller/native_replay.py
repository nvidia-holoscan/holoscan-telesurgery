# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Drive the shared replay API from the native window's responsive event loop."""

import time
from concurrent.futures import ThreadPoolExecutor


def recording_for(records, robot, device):
    return next(
        (
            item
            for item in records
            if robot.get("simulation")
            and robot.get("kind") == f"{item['environment']}-sim"
            and item["device"] == device
            and robot["id"].split(":")[-1] in item["streams"]
        ),
        None,
    )


class NativeReplay:
    def __init__(self, client, control):
        self.client, self.control = client, control
        # Each lane has at most one request: feedback/start, heartbeat, cancel.
        # A slow network reply must not block the window's heartbeat or Stop.
        self.worker = ThreadPoolExecutor(max_workers=3, thread_name_prefix="robot-replay")
        self.pending = self.heartbeat = self.cancelling = None
        self.cancel_needed = self.active = False
        self.robot = self.recording = self.result = None
        self.generation = 0
        self.last_heartbeat = 0
        self.phase = self.status = ""
        self.input = None

    @property
    def busy(self):
        return bool(
            self.active or self.pending or self.heartbeat or self.cancelling or self.cancel_needed
        )

    def start(self, robot, recording):
        if (
            self.busy
            or self.control.owned != robot["id"]
            or self.control.releasing
            or not recording_for([recording], robot, recording["device"])
        ):
            return False
        self.control.stop()
        self.robot, self.recording = robot["id"], recording["id"]
        self.speed_supported = bool(robot.get("controls", {}).get("speed_deg_s"))
        self.generation += 1
        self.active = True
        self.phase, self.status = "preparing", "Preparing replay…"
        self.result = None
        self.input = None
        self.last_heartbeat = 0
        return True

    def stop(self, reason="operator stopped replay", *, completed=False):
        if not self.active:
            return
        self.active = False
        self.input = None
        self.generation += 1
        self.result = None
        self.cancel_needed = not completed
        self.status = "Replay complete" if completed else f"Replay stopped · {reason}"
        self.control.stop()

    def poll(self, now):
        if self.cancelling and self.cancelling.done():
            # Loss of ownership/disconnection already stops the remote replay.
            self.cancelling = None
        if self.heartbeat and self.heartbeat[1].done():
            generation, future = self.heartbeat
            self.heartbeat = None
            try:
                future.result()
            except Exception as exc:
                if self.active and generation == self.generation:
                    self.stop(str(exc))
        if self.pending and self.pending[-1].done():
            method, generation, started, future = self.pending
            self.pending = None
            try:
                result = future.result()
            except Exception as exc:
                if self.active and generation == self.generation:
                    self.stop(str(exc))
            else:
                if generation != self.generation:
                    # Stop may race a start that is still joining the patient.
                    # Cancel again after its reply; never forward a late read.
                    if method == "replay.start":
                        self.cancel_needed = True
                elif method == "replay.start":
                    self.phase = "playing"
                else:
                    self.result = started, result
        if self.cancel_needed and self.cancelling is None:
            self.cancel_needed = False
            self.cancelling = self.worker.submit(
                self.client.action, "replay.cancel", {"id": self.robot}
            )
        if not self.active:
            return
        if self.control.failed or self.control.owned != self.robot or self.control.releasing:
            self.stop(self.control.error or "control no longer available")
            return
        if self.heartbeat is None and now - self.last_heartbeat >= 0.1:
            self.last_heartbeat = now
            self.heartbeat = (
                self.generation,
                self.worker.submit(self.client.action, "replay.heartbeat", {"id": self.robot}),
            )
        if not self.control.ready or self.pending:
            return
        if self.phase == "finishing":
            self.stop(completed=True)
            return
        if self.result:
            started, result = self.result
            self.result = None
            if not result.get("feedback_paced") and now - started > 0.2:
                self.stop("timed replay response delayed")
                return
            state = result.get("state", {})
            if state.get("sequence", -1) > self.control.reply.get(self.robot, {}).get(
                "sequence", -1
            ):
                self.control.reply[self.robot] = state
            self.status = (
                "Waiting for the other surgeon…"
                if result.get("waiting")
                else result.get("waiting_reason", "Waiting at handoff checkpoint…")
                if result.get("waiting_peer")
                else f"Replaying · {int(result['elapsed'])} s"
                + (" · waiting for feedback" if result.get("waiting_feedback") else "")
            )
            if result.get("request"):
                mode, command = result["request"]
                if mode == "release":
                    self.control.stop()
                elif not self.control.move(
                    self.robot,
                    mode,
                    command,
                    result.get("speed_deg_s") if self.speed_supported else None,
                    replay_run=result["run"],
                ):
                    self.stop("replay motion was interrupted")
                    return
            self.input = result.get("input")
            if result["done"]:
                self.input = None
                self.control.stop()
                self.phase = "finishing"
            return
        method = "replay.start" if self.phase == "preparing" else "replay.read"
        params = {"id": self.robot}
        if method == "replay.start":
            params["recording"] = self.recording
        self.pending = (
            method,
            self.generation,
            now,
            self.worker.submit(self.client.action, method, params),
        )

    def close(self):
        self.stop("controller closed")
        while self.busy:
            self.poll(time.monotonic())
            time.sleep(0.01)
        self.worker.shutdown(wait=True, cancel_futures=True)
