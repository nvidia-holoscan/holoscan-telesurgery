# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Versius raw frames carry a complete source trace without requiring Isaac Sim."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from telesurgery_core.diagnostics.trace import source
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.formats import decode_raw
from telesurgery_sim.runtime.versius import capture_frame


def test_raw_capture_records_acquisition_and_packing(monkeypatch):
    clock = Mock(side_effect=[100, 140, 160])
    monkeypatch.setattr("telesurgery_sim.runtime.versius.time.monotonic_ns", clock)
    rgb = np.full((2, 3, 3), [10, 20, 30], dtype=np.uint8)

    def read(kind):
        assert kind == "rgb" and clock.call_count == 1
        return SimpleNamespace(numpy=lambda: rgb), None

    header, data = capture_frame(SimpleNamespace(get_data=read), 7, 4)
    header = VideoHeader.decode(header.encode())
    assert header.sequence == 7 and header.sim_command_sequence == 4
    assert header.source_started_ns == 100 and header.encoded_ns == 160
    assert source(header) == {
        "at_ns": 160,
        "stages": {"acquisition_ms": 40 / 1e6, "encoder_queue_ms": 0, "pack_ms": 20 / 1e6},
        "error_ms": 0,
    }
    np.testing.assert_array_equal(decode_raw(header, data).image, rgb[..., ::-1])


@pytest.mark.parametrize("pixels", [None, np.empty((0, 0, 3), dtype=np.uint8)])
def test_missing_camera_pixels_do_not_publish_a_frame(pixels):
    camera = SimpleNamespace(
        get_data=lambda _: (None if pixels is None else SimpleNamespace(numpy=lambda: pixels), None)
    )
    assert capture_frame(camera, 1, 0) is None
