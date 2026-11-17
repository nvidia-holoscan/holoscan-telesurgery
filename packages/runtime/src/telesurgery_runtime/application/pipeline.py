# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded application calls executed by real Holoscan graphs."""

from collections import deque
from concurrent.futures import Future, InvalidStateError
from queue import Empty, Full, Queue
from threading import Lock
from time import monotonic

from telesurgery_runtime.backends.sdk import ApplicationSession, backend


class Calls:
    def __init__(self, idle=None, interval=0.1):
        self.pending = Queue(maxsize=64)
        self.active = None
        self.idle, self.interval, self.next_idle = idle, interval, 0.0
        self.was_idle = False

    def compute(self):
        # Expire queued work even while another invocation is stalled. Never
        # finish the active future early: its function may still be running.
        expired = []
        with self.pending.mutex:
            for _ in range(len(self.pending.queue)):
                item = self.pending.queue.popleft()
                if item[0].done() or monotonic() > item[1]:
                    expired.append(item[0])
                else:
                    self.pending.queue.append(item)
            if expired:
                self.pending.not_full.notify_all()
        for future in expired:
            if not future.done():
                try:
                    future.set_exception(TimeoutError("Request expired before execution"))
                except InvalidStateError:
                    pass  # Its caller cancelled it while we expired the queue.
        # One outstanding call prevents latest-frame SDK channels dropping requests.
        if self.active is not None and not self.active.done():
            return None
        if (
            self.idle is not None
            and monotonic() >= self.next_idle
            and (not self.was_idle or self.pending.empty())
        ):
            self.next_idle = monotonic() + self.interval
            item = (Future(), float("inf"), self.idle, ())
            self.was_idle = True
        else:
            try:
                item = self.pending.get_nowait()
                self.was_idle = False
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

    def __init__(self, name, *, idle=None, interval=0.1):
        self.name = name
        self.source = Calls(idle, interval)
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
            try:
                self.session.__exit__(None, None, None)
            finally:
                self.source.stop()
            self.session = None


class Frames:
    """Encoded frames per camera, in arrival order.

    A predicted frame is only useful after the one before it, so a short backlog
    stays in order. A keyframe replaces whatever is waiting, which keeps only the
    newest frame of an intra-only stream. A camera that falls ``backlog`` frames
    behind drops them; the receiver then recovers with an IDR.
    """

    def __init__(self, backlog=8):
        self.pending, self.backlog = {}, backlog
        self.lock = Lock()

    def put(self, key, value, keyframe=True):
        with self.lock:
            queue = self.pending.setdefault(key, deque())
            if keyframe or len(queue) >= self.backlog:
                queue.clear()
            queue.append(value)

    def compute(self):
        with self.lock:
            key = next((key for key, queue in self.pending.items() if queue), None)
            if key is None:
                return None
            queue = self.pending.pop(key)
            self.pending[key] = queue  # Cameras take turns.
            return queue.popleft()

    @property
    def wake(self):
        """A source stage that signals waiting frames without removing them."""
        frames = self

        class Wake:
            def compute(self):
                with frames.lock:
                    return True if any(frames.pending.values()) else None

        return Wake()


class Deliver:
    """Hand every waiting frame to the callback, in order.

    The graph edge into this stage keeps one message and may drop an older one, so
    it only carries a wake-up; the frames themselves stay in ``frames`` until read.
    """

    def __init__(self, callback, frames):
        self.callback, self.source, self.frames = callback, frames, 0

    def compute(self, _):
        while (value := self.source.compute()) is not None:
            self.callback(value)
            self.frames += 1


class VideoBridge:
    """Independent graph, so browser delivery cannot block robot calls."""

    def __init__(self, callback):
        self.source = Frames()
        self.sink = Deliver(callback, self.source)
        self.session = ApplicationSession(
            backend("pipeline").build("surgeon_video", [self.source.wake, self.sink], 1000)
        )

    def start(self):
        self.session.__enter__()

    def put(self, camera, header, payload, timing=None):
        self.source.put(camera, (camera, header, payload, timing), header.get("keyframe", True))

    def close(self):
        self.session.__exit__(None, None, None)
        self.session = None
