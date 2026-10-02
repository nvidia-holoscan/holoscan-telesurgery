# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Raw transport preserves every pixel and accounts for buffer preparation separately."""

import builtins
import time
from dataclasses import replace

import numpy as np
import pytest
from telesurgery_core.diagnostics.trace import source
from telesurgery_core.transport.protocol import MAX_VIDEO, VideoHeader, decode_video
from telesurgery_core.video.codecs import create_codec
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame


def test_raw_4k_is_exact_without_gpu_or_codec_libraries(monkeypatch):
    original_import = builtins.__import__

    def checked(name, *args, **kwargs):
        assert name.split(".")[0] not in {"cupy", "PyNvVideoCodec", "nvidia"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked)
    config = Config(codec="raw-bgr8")
    encoder, decoder = create_codec(config, encode=True), create_codec(config, encode=False)
    try:
        # Noncontiguous input must be packed correctly without changing channel order.
        pixels = np.arange(2160 * 3840 * 3, dtype=np.uint8).reshape(2160, 3840, 3)[..., ::-1]
        ready = time.perf_counter_ns()
        header = VideoHeader(42, time.time_ns(), 3840, 2160, source_started_ns=ready)
        encoded, data = encoder.encode(Frame(header, pixels, ready_ns=ready))
        assert len(data) == pixels.nbytes > MAX_VIDEO
        assert encoded.encode_ns == 0 and encoded.pack_ns > 0
        assert encoded.captured_ns == header.captured_ns and encoded.sequence == 42
        assert sum(source(encoded)["stages"].values()) == pytest.approx(
            (encoded.encoded_ns - ready) / 1e6
        )
        assert "encode_ms" not in source(encoded)["stages"]
        parsed, payload = decode_video([encoded.encode(), data])
        image = decoder.decode(parsed, payload).image
        np.testing.assert_array_equal(image, pixels)
        pixels[:] = 0
        assert image.max() == 255  # The transmitted frame owns its bytes.
        for damaged in (data[:-1], data + b"x"):
            with pytest.raises(ValueError, match="exact raw"):
                decode_video([encoded.encode(), damaged])
            with pytest.raises(ValueError, match="exact raw"):
                decoder.decode(encoded, damaged)
        with pytest.raises(ValueError, match="bounded compressed"):
            decode_video([replace(encoded, codec="h264").encode(), data])
    finally:
        encoder.close()
        decoder.close()
