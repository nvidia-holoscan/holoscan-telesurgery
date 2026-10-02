# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded JSON-RPC connection to a local device controller."""

import json


class RpcClient:
    """One bounded request/reply at a time; never replay a motion after failure."""

    def __init__(self, uri: str, *, timeout=0.5):
        import websocket

        self.socket = websocket.create_connection(uri, timeout=timeout, enable_multithread=False)
        self.sequence = 0

    def send(self, request: dict):
        self.sequence += 1
        message = {**request, "id": self.sequence}
        self.socket.send(json.dumps(message, allow_nan=False))
        reply = json.loads(self.socket.recv())
        if not isinstance(reply, dict) or reply.get("id") != self.sequence or "error" in reply:
            raise RuntimeError(f"Controller rejected request {self.sequence}: {reply}")
        return reply.get("result")

    def close(self):
        self.socket.close()
