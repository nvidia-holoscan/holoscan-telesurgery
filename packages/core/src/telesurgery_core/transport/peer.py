# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded bidirectional RPC and latest-frame video over an application TCP connection."""

import asyncio
import contextlib
import json
import secrets
import struct
import time
from collections import OrderedDict
from itertools import count

from telesurgery_core.diagnostics.clock import Clock, PeerClock
from telesurgery_core.diagnostics.trace import mark, wire

MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 32 * 1024 * 1024
PREFIX = struct.Struct("!II")


class Peer:
    def __init__(
        self,
        reader,
        writer,
        handler,
        event_handler=None,
        *,
        clock=None,
        video_sent=None,
        video_stage="send_queue_ms",
    ):
        self.id = secrets.token_urlsafe(24)
        self.reader, self.writer = reader, writer
        self.handler, self.event_handler = handler, event_handler
        self.pending = {}
        self.requests = set()
        self.reliable = asyncio.Queue(maxsize=64)
        self.frames = OrderedDict()
        self.wake = asyncio.Event()
        self.closed = asyncio.Event()
        self.sender = self.receiver = self.prober = None
        self.relative_clock = PeerClock()
        self.probes = {}
        self.clock = clock or Clock()
        self.video_sent, self.video_stage = video_sent, video_stage

    def start(self):
        self.sender = asyncio.create_task(self._send())
        self.receiver = asyncio.create_task(self._receive())
        self.prober = asyncio.create_task(self._probe())
        return self

    def delivery(self, sent, *, frame_bytes=None):
        return {**self.relative_clock.delivery(self.clock, sent), "frame_bytes": frame_bytes}

    async def _probe(self):
        try:
            for attempt in count():
                if self.relative_clock.domain == self.clock.domain and self.clock.domain:
                    return
                self._queue({"type": "clock", "id": secrets.token_hex(12)})
                await asyncio.sleep(0.2 if attempt < 5 else 2)
        except (ConnectionError, RuntimeError):
            return

    def _queue(self, header, payload=b"", *, stream=None):
        if self.closed.is_set():
            raise ConnectionError("Endpoint disconnected")
        if stream is None:
            try:
                self.reliable.put_nowait((header, payload))
            except asyncio.QueueFull as exc:
                raise RuntimeError("Endpoint request queue is full") from exc
        else:
            if stream not in self.frames and len(self.frames) >= 32:
                self.frames.popitem(last=False)
            self.frames[stream] = (header, payload)
        self.wake.set()

    async def call(self, method, params=None, *, timeout=10):
        key = secrets.token_hex(12)
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            self._queue({"type": "request", "id": key, "method": method, "params": params or {}})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(key, None)

    def event(self, name, params, payload=b"", *, stream=None):
        self._queue({"type": "event", "name": name, "params": params}, payload, stream=stream)

    def clear_frames(self):
        self.frames.clear()

    async def _send(self):
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                while not self.reliable.empty() or self.frames:
                    if not self.reliable.empty():
                        header, payload = self.reliable.get_nowait()
                    else:
                        _, (header, payload) = self.frames.popitem(last=False)
                    if header["type"] == "request" and header["id"] not in self.pending:
                        continue
                    if header["type"] == "clock":
                        now = time.monotonic_ns()
                        self.probes = {
                            k: v for k, v in self.probes.items() if now - v < 5_000_000_000
                        }
                        self.probes[header["id"]] = now
                    elif header["type"] == "clock_reply":
                        header = {**header, "t2": time.monotonic_ns()}
                    trace = None
                    if header.get("name") == "video":
                        params = dict(header["params"])
                        stamp = self.clock.stamp()
                        trace = mark(params.get("trace"), self.video_stage, stamp["mono_ns"])
                        params.update(timing=stamp, trace=wire(trace))
                        header = {**header, "params": params}
                    raw = json.dumps(header, allow_nan=False, separators=(",", ":")).encode()
                    if len(raw) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
                        raise ValueError("Application message exceeds size limit")
                    self.writer.write(PREFIX.pack(len(raw), len(payload)))
                    self.writer.write(raw)
                    self.writer.write(payload)
                    if header.get("name") == "video" and self.video_sent:
                        self.video_sent(
                            params["camera"], trace, PREFIX.size + len(raw) + len(payload)
                        )
                    await asyncio.wait_for(self.writer.drain(), 3)
        except (ConnectionError, OSError, ValueError, TimeoutError):
            pass
        finally:
            self._disconnect()

    async def _receive(self):
        try:
            while True:
                hsize, psize = PREFIX.unpack(await self.reader.readexactly(PREFIX.size))
                if not 0 < hsize <= MAX_HEADER or psize > MAX_PAYLOAD:
                    raise ValueError("Invalid application message size")
                header = json.loads(await self.reader.readexactly(hsize))
                payload = await self.reader.readexactly(psize)
                if not isinstance(header, dict):
                    raise ValueError("Expected a message object")
                kind = header.get("type")
                received = time.monotonic_ns()
                if kind == "clock":
                    self._queue(
                        {
                            "type": "clock_reply",
                            "id": header["id"],
                            "domain": self.clock.domain,
                            "t1": received,
                        }
                    )
                elif kind == "clock_reply":
                    sent = self.probes.pop(header.get("id"), None)
                    if sent is not None:
                        self.relative_clock.observe(
                            header.get("domain"), sent, header.get("t1"), header.get("t2"), received
                        )
                elif kind == "response":
                    future = self.pending.get(header.get("id"))
                    if future is not None and not future.done():
                        if "error" in header:
                            future.set_exception(RuntimeError(str(header["error"])))
                        else:
                            future.set_result(header.get("result"))
                elif kind == "request":
                    if len(self.requests) >= 32:
                        raise ValueError("Too many outstanding requests")
                    task = asyncio.create_task(self._request(header))
                    self.requests.add(task)
                    task.add_done_callback(self.requests.discard)
                elif kind == "event" and self.event_handler:
                    if header.get("name") == "video":
                        header["params"]["transport_bytes"] = PREFIX.size + hsize + psize
                    await self.event_handler(
                        self, header.get("name"), header.get("params"), payload
                    )
                else:
                    raise ValueError("Unknown application message")
        except (
            asyncio.IncompleteReadError,
            ConnectionError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ):
            pass
        finally:
            self._disconnect()

    async def _request(self, header):
        reply = {"type": "response", "id": header.get("id")}
        try:
            if not isinstance(header.get("params"), dict):
                raise ValueError("Expected request parameters")
            reply["result"] = await self.handler(self, header.get("method"), header["params"])
        except Exception as exc:
            reply["error"] = str(exc)
        with contextlib.suppress(ConnectionError, RuntimeError):
            self._queue(reply)

    def _disconnect(self):
        if self.closed.is_set():
            return
        self.closed.set()
        self.writer.close()
        self.frames.clear()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError("Endpoint disconnected"))
        current = asyncio.current_task()
        for task in (self.sender, self.receiver, self.prober, *self.requests):
            if task is not None and task is not current:
                task.cancel()

    async def close(self):
        self._disconnect()
        tasks = [
            t for t in (self.sender, self.receiver, self.prober, *self.requests) if t is not None
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except (ConnectionError, OSError, TimeoutError):
            self.writer.transport.abort()
