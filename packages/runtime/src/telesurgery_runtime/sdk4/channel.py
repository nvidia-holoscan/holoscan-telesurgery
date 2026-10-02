# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded Python ownership with native SDK 4 scheduling notifications."""

from threading import Lock


class LatestChannel:
    """One producer/consumer, one owned pending payload, native uint64 GXF tokens.

    SDK 4.6 can destroy an overflowed GILGuardedPyObject while holding its queue
    mutex, deadlocking against Python receive(). Keep Python destruction outside
    GXF locks. Integer tokens still trigger the real SDK dataflow scheduler.
    """

    def __init__(self):
        self.lock = Lock()
        self.value = None
        self.sequence = 0

    def send(self, output, value):
        with self.lock:
            previous, self.value = self.value, value
            self.sequence += 1
            sequence = self.sequence
        del previous
        output.emit(sequence, "out", emitter_name="uint64_t")

    def receive(self, input):
        input.receive("in")
        with self.lock:
            value, self.value = self.value, None
        # Several notifications may refer to an already-consumed latest payload.
        return value
