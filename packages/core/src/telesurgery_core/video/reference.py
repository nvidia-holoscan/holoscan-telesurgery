# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Receiver-side reference tracking for IPPP streams over lossy, latest-frame hops."""

from __future__ import annotations

import time

# The node touches this file beside a camera's settings to request an IDR from its worker.
KEYFRAME_SUFFIX = ".idr"

# A receiver that cannot decode asks for a new IDR at most this often.
REFRESH_INTERVAL = 0.5


class MissingReference(ValueError):
    """A delta frame arrived without its predecessor; wait for the next keyframe."""


class ReferenceChain:
    """Accept a delta frame only when it directly follows the last accepted frame.

    Every hop between encoder and decoder may drop frames to stay current. The
    encoder numbers frames within each GOP, so a receiver sees any loss as a gap,
    discards deltas until the next IDR, and asks for one.
    """

    def __init__(self, *, interval: float = REFRESH_INTERVAL, clock=time.monotonic):
        self.last = None
        self.interval, self.clock, self.next_request = interval, clock, 0.0

    def accept(self, header) -> bool:
        if header.keyframe:
            self.last = header.gop, header.gop_index
            return True
        if self.last is not None and self.last == (header.gop, header.gop_index - 1):
            self.last = header.gop, header.gop_index
            return True
        self.last = None
        return False

    def reset(self) -> None:
        self.last = None

    def refresh_due(self) -> bool:
        """True when the caller should request a keyframe now; rate-limited."""
        now = self.clock()
        if now < self.next_request:
            return False
        self.next_request = now + self.interval
        return True
