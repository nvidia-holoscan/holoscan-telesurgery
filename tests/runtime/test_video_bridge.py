# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The surgeon's video graph delivers a burst of predicted frames complete and in order."""

import time

import pytest

pytestmark = pytest.mark.sdk


def test_bridge_delivers_bursts_in_order_through_the_sdk_graph():
    pytest.importorskip("holoscan")
    from telesurgery_runtime.application.pipeline import VideoBridge

    delivered = []
    bridge = VideoBridge(delivered.append)
    bridge.start()
    try:
        expected = []
        for burst in range(20):
            # Several frames arrive between two ticks of the graph.
            for index in range(6):
                header = {"keyframe": index == 0, "gop": burst, "gop_index": index}
                bridge.put("camera", header, b"frame")
                expected.append((burst, index))
            # The next burst starts with a keyframe, which replaces anything still waiting.
            deadline = time.monotonic() + 10
            while len(delivered) < len(expected) and time.monotonic() < deadline:
                time.sleep(0.001)
            assert [(h["gop"], h["gop_index"]) for _, h, _, _ in delivered] == expected
    finally:
        bridge.close()
