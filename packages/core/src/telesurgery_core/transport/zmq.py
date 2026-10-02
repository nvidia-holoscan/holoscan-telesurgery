# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded ZeroMQ sockets for streaming and the local simulator gateway."""

import zmq
from telesurgery_core.transport.protocol import MAX_VIDEO


def open_socket(kind: int, endpoint: str, *, bind: bool, max_size: int = MAX_VIDEO) -> zmq.Socket:
    sock = zmq.Context.instance().socket(kind)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.SNDHWM, 2)
    sock.setsockopt(zmq.RCVHWM, 2)
    sock.setsockopt(zmq.MAXMSGSIZE, max_size)
    if kind == zmq.SUB:
        sock.setsockopt(zmq.SUBSCRIBE, b"")
    if kind == zmq.PUSH:
        sock.setsockopt(zmq.IMMEDIATE, 1)
    try:
        (sock.bind if bind else sock.connect)(endpoint)
    except Exception:
        sock.close()
        raise
    return sock


def latest(sock: zmq.Socket, *, limit: int = 8) -> list[bytes] | None:
    """Drain a bounded batch and return its newest message, without blocking."""
    result = None
    for _ in range(limit):
        try:
            result = sock.recv_multipart(zmq.NOBLOCK)
        except zmq.Again:
            break
    return result
