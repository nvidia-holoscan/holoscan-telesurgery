# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded application calls executed by real Holoscan graphs."""

from concurrent.futures import Future
from queue import Empty, Full, Queue
from threading import Lock
from time import monotonic

from telesurgery_runtime.sdk import ApplicationSession, backend


class Calls:
    def __init__(self):
        self.pending = Queue(maxsize=64)
        self.active = None

    def compute(self):
        # One outstanding call prevents latest-frame SDK channels dropping requests.
        if self.active is not None and not self.active.done():
            return None
        try:
            item = self.pending.get_nowait()
        except Empty:
            return None
        self.active = item[0]
        return item

    def stop(self):
        if self.active is not None and not self.active.done():
            self.active.set_exception(RuntimeError("Holoscan endpoint stopped"))
        while True:
            try:
                future = self.pending.get_nowait()[0]
            except Empty:
                break
            if not future.done():
                future.set_exception(RuntimeError("Holoscan endpoint stopped"))


class Invoke:
    def compute(self, item):
        future, deadline, function, args = item
        if not future.set_running_or_notify_cancel():
            return None
        try:
            if monotonic() > deadline:
                raise TimeoutError("Request expired before execution")
            result = function(*args)
        except Exception as exc:
            return future, None, exc
        return future, result, None


class Complete:
    def compute(self, item):
        future, result, error = item
        if not future.done():
            if error is None:
                future.set_result(result)
            else:
                future.set_exception(error)


class Executor:
    """Request -> invocation -> result graph shared by patient and surgeon endpoints."""

    def __init__(self, name):
        self.name = name
        self.source = Calls()
        self.session = None

    def start(self):
        session = ApplicationSession(
            backend("pipeline").build(self.name, [self.source, Invoke(), Complete()], 1000)
        )
        session.__enter__()
        self.session = session
        return self

    def submit(self, function, *args, timeout=2):
        future = Future()
        if self.session is None or not self.session.is_running():
            future.set_exception(RuntimeError("Holoscan endpoint is not running"))
            return future
        try:
            self.source.pending.put_nowait((future, monotonic() + timeout, function, args))
        except Full:
            future.set_exception(RuntimeError("Holoscan endpoint is busy"))
        return future

    def close(self):
        if self.session is not None:
            session, self.session = self.session, None
            try:
                session.__exit__(None, None, None)
            finally:
                self.source.stop()


class Frames:
    def __init__(self):
        self.pending = {}
        self.lock = Lock()

    def put(self, key, value):
        with self.lock:
            self.pending[key] = value

    def compute(self):
        with self.lock:
            if not self.pending:
                return None
            key = next(iter(self.pending))
            return self.pending.pop(key)


class Deliver:
    def __init__(self, callback):
        self.callback, self.frames = callback, 0

    def compute(self, value):
        self.callback(value)
        self.frames += 1


class VideoBridge:
    """Independent latest-frame graph, so browser delivery cannot block robot calls."""

    def __init__(self, callback):
        self.source, self.sink = Frames(), Deliver(callback)
        self.session = ApplicationSession(
            backend("pipeline").build("surgeon_video", [self.source, self.sink], 1000)
        )

    def start(self):
        self.session.__enter__()

    def put(self, camera, header, payload, timing=None):
        self.source.put(camera, (camera, header, payload, timing))

    def close(self):
        self.session.__exit__(None, None, None)
        self.session = None
