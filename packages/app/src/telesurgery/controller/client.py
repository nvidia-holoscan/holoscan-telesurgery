# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Use the same surgeon API as the dashboard, with one outstanding control request."""

import json
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class Client:
    def __init__(self, server, certificate=None):
        url = urlsplit(server)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("Use a surgeon dashboard URL, such as http://127.0.0.1:8002")
        self.server = server.rstrip("/")
        self.context = ssl.create_default_context(cafile=certificate) if certificate else None

    def request(self, path, body=None):
        request = Request(
            self.server + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Origin": self.server},
        )
        try:
            with urlopen(request, timeout=8, context=self.context) as response:  # nosec B310
                return json.load(response)
        except HTTPError as exc:
            try:
                message = json.load(exc).get("error", str(exc))
            except (ValueError, AttributeError):
                message = str(exc)
            raise RuntimeError(message) from exc
        except URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise RuntimeError(
                    "Cannot verify the dashboard certificate for "
                    f"{urlsplit(self.server).hostname}. "
                    "Use a trusted certificate that includes this local address or hostname."
                ) from exc
            raise

    def status(self):
        return self.request("/api/status")

    def action(self, method, params):
        return self.request("/api/action", {"action": method, "params": params})["result"]


class Control:
    """Resample after replies; never enqueue motion behind a slow or interrupted request."""

    def __init__(self, client):
        self.client = client
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="robot-input")
        self.pending = None
        self.owned = None
        self.releasing = False
        self.release_failed = None
        self.stopping = self.moving = False
        self.last_renew = 0
        self.reply = {}
        self.error = ""
        self.failed = False

    @property
    def ready(self):
        return (
            self.pending is None
            and not self.releasing
            and not self.stopping
            and not self.release_failed
        )

    def _send(self, method, params):
        if self.pending is not None:
            return False
        self.pending = (
            method,
            params["id"],
            self.worker.submit(self.client.action, method, params),
        )
        return True

    def acquire(self, robot):
        if not self.ready or self.owned:
            return False
        self.owned = robot  # Keep the credential available if the reply is interrupted.
        self.error = ""
        return self._send("robot.acquire", {"id": robot})

    def adopt(self, robot):
        """Accept an explicit UI handoff by validating the existing lease only."""
        if not self.ready or self.owned:
            return False
        self.owned = robot
        self.error = ""
        return self._send("robot.renew", {"id": robot})

    def move(self, robot, mode, command, speed, *, replay_run=None):
        if not self.ready or self.owned != robot:
            return False
        self.error = ""
        self.moving = True
        if mode == "grip":
            command = {"velocity": command}
        return self._send(
            "robot.move",
            {
                "id": robot,
                "mode": mode,
                "command": command,
                **({"speed_deg_s": speed} if speed is not None else {}),
                **({"replay": True, "replay_run": replay_run} if replay_run is not None else {}),
            },
        )

    def stop(self):
        self.stopping = bool(self.owned and self.moving)

    def release(self, robot=None):
        self.owned = self.owned or self.release_failed or robot
        self.release_failed = None
        self.releasing = bool(self.owned)

    def poll(self, now):
        if self.pending is not None:
            method, robot, future = self.pending
            if not future.done():
                return
            self.pending = None
            try:
                result = future.result()
                if isinstance(result, dict):
                    self.reply[robot] = result
            except Exception as exc:
                self.error = str(exc)
                self.failed = True
                if method == "robot.release":
                    self.release_failed = robot
                if method == "robot.move" and self.owned:
                    self.stop()
                elif method != "robot.release":
                    self.release()
            if method == "robot.hold":
                self.stopping = self.moving = False
            if method == "robot.release":
                if not self.release_failed:
                    self.error = ""
                self.owned = None
                self.releasing = False
                self.stopping = self.moving = False
            self.last_renew = now
        if self.releasing and self.owned:
            self._send("robot.release", {"id": self.owned})
        elif self.stopping and self.owned:
            self._send("robot.hold", {"id": self.owned})
        elif self.owned and now - self.last_renew >= 0.5:
            self._send("robot.renew", {"id": self.owned})

    def feedback(self, robot):
        state = robot.get("state") or {}
        reply = self.reply.get(robot["id"], {})
        return reply if reply.get("sequence", -1) > state.get("sequence", -1) else state

    def close(self):
        self.release()
        deadline = time.monotonic() + 9
        while (self.owned or self.pending) and time.monotonic() < deadline:
            self.poll(time.monotonic())
            time.sleep(0.01)
        self.worker.shutdown(wait=True, cancel_futures=True)
