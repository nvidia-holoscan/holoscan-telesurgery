# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small SDK 5 graph building blocks shared by video and control."""

import holoscan as hs


class PeriodicOp(hs.Operator):
    """A clock-driven source; device and network reads must be bounded."""

    hz = hs.Param(30, range=(1, 1000))

    def contract(self):
        return hs.Contract().trigger(hs.OnClock(period=hs.time.ns(1_000_000_000 // self.hz)))


def connect(graph, output, input):
    """Bound pending work to one sample so congestion cannot accumulate stale video."""
    graph.add_flow(output, input, queue_depth=1, queue_policy=hs.QueuePolicy.DROP_OLDEST)
