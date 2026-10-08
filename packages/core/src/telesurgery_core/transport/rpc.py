# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded JSON-RPC connection to a local device controller."""

import json
import time

import websocket


class RpcClient:
    """One bounded request/reply at a time; never replay a motion after failure."""

    def __init__(self, uri: str, *, timeout=0.5, broadcast=False):
        try:
            self.socket = websocket.create_connection(
                uri, timeout=timeout, enable_multithread=False
            )
        except (OSError, websocket.WebSocketException) as exc:
            raise ConnectionError(f"Controller connection failed: {exc}") from exc
        self.sequence = 0
        self.timeout = timeout
        self.broadcast = broadcast

    def notify(self, request):
        try:
            self.socket.send(json.dumps({"jsonrpc": "2.0", **request}, allow_nan=False))
        except (OSError, websocket.WebSocketException) as exc:
            raise ConnectionError(f"Controller send failed: {exc}") from exc

    def command(self, request, query):
        """Observe a notification's rejection before accepting the following query reply."""
        self.sequence += 1
        command_id = self.sequence
        self.notify({**request, "id": command_id})
        return self.send(query, reject_ids=(command_id,))

    def send(self, request: dict, *, reject_ids=()):
        self.sequence += 1
        message = {"jsonrpc": "2.0", **request, "id": self.sequence}
        self.notify(message)
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                self.socket.settimeout(max(0.001, deadline - time.monotonic()))
                reply = json.loads(self.socket.recv())
                if isinstance(reply, dict) and "method" in reply:
                    continue  # Vendor identity and collision notifications are not replies.
                if isinstance(reply, dict) and reply.get("id") in reject_ids and "error" in reply:
                    error = reply["error"]
                    reason = (
                        error.get("message", "Unknown error") if isinstance(error, dict) else error
                    )
                    raise RuntimeError(f"Controller rejected request: {reason}")
                if self.broadcast and isinstance(reply, dict) and reply.get("id") != self.sequence:
                    continue
                if not isinstance(reply, dict) or reply.get("id") != self.sequence:
                    raise RuntimeError("Controller returned an invalid response")
                if "error" in reply:
                    error = reply["error"]
                    reason = (
                        error.get("message", "Unknown error") if isinstance(error, dict) else error
                    )
                    raise RuntimeError(f"Controller rejected request: {reason}")
                return reply.get("result")
            raise TimeoutError("Controller did not reply")
        except (OSError, websocket.WebSocketException) as exc:
            raise ConnectionError(f"Controller reply failed: {exc}") from exc
        finally:
            self.socket.settimeout(self.timeout)

    def close(self):
        self.socket.close(timeout=self.timeout)
