# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Depth keeps its values, frame association and bounded decoding across codecs."""

import time
import zlib
from dataclasses import replace

import numpy as np
import pytest
from telesurgery_core.diagnostics.trace import source
from telesurgery_core.transport.protocol import VideoHeader, decode_video
from telesurgery_core.video import depth
from telesurgery_core.video.codecs import CodecWorker
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame


def test_depth_attachment_validates_shape_and_compression():
    header = VideoHeader(1, 1, 8, 8)
    values = np.arange(64, dtype=np.float32).reshape(8, 8) / 1000
    values[0, 0] = np.nan
    header, data = depth.attach(header, b"color", values)
    assert decode_video([header.encode(), data]) == (header, data)
    color, packed = depth.split(header, data)
    assert color == b"color"
    np.testing.assert_array_equal(depth.unpack(header, packed), values)
    for invalid in [
        packed[:-1],
        packed + b"trailing",
        zlib.compress(bytes(257)),
        zlib.compress(bytes(255)),
    ]:
        with pytest.raises(ValueError):
            depth.unpack(header, invalid)
    with pytest.raises(ValueError):
        depth.attach(header, color, values[:4])
    with pytest.raises(ValueError):
        decode_video([replace(header, depth_bytes=len(data)).encode(), data])


@pytest.mark.gpu
@pytest.mark.parametrize("codec", ["raw-bgr8", "h264", "h265", "nvjpeg"])
def test_depth_roundtrip_and_stage_timing(codec):
    config = Config(codec=codec, width=320, height=240)
    encoder = CodecWorker(config, encode=True)
    decoder = CodecWorker(config, encode=False)
    try:
        values = np.linspace(0, 3, 320 * 240, dtype=np.float32).reshape(240, 320)
        ready = time.perf_counter_ns()
        header = VideoHeader(73, time.time_ns(), 320, 240, source_started_ns=ready)
        pixels = np.full((240, 320, 3), 128, np.uint8)
        packet = encoder.encode(Frame(header, pixels, ready_ns=ready, depth=values))
        header, data = decode_video([packet[0].encode(), packet[1]])
        frame = decoder.decode(header, data)
        np.testing.assert_array_equal(frame.depth, values)
        assert frame.header.sequence == 73
        assert frame.image.shape == pixels.shape
        trace = source(header)
        assert trace is not None
        assert trace["stages"]["pack_ms"] > 0
        assert sum(trace["stages"].values()) == pytest.approx((header.encoded_ns - ready) / 1e6)
    finally:
        decoder.close()
        encoder.close()


@pytest.mark.gpu
def test_native_depth_preserves_color_and_masks_missing_measurements():
    import cupy as cp

    color = cp.full((8, 8, 3), 100, cp.uint8)
    values = np.ones((8, 8), np.float32)
    values[0] = np.nan
    overlay = depth.render(color, values, mode="overlay")
    np.testing.assert_array_equal(cp.asnumpy(overlay[0]), cp.asnumpy(color[0]))
    side = depth.render(color, values, mode="side")
    assert side.shape == (8, 16, 3)
    np.testing.assert_array_equal(cp.asnumpy(side[:, :8]), cp.asnumpy(color))
    assert not cp.any(depth.render(color, None, mode="depth"))
