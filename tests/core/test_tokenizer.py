# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The neural wire format is fixed, bounded and independent of GPU libraries."""

from dataclasses import replace

import numpy as np
import pytest
from telesurgery_core.transport.protocol import VideoHeader, decode_video
from telesurgery_core.video.tokenizer import unpack_tokens
from telesurgery_core.video.tokenizer_model import CODEC, PROFILE, payload_size, token_shape


@pytest.mark.parametrize("width,height", [(1280, 720), (1920, 1080)])
def test_token_payload_profile_byte_order_and_bounds(width, height):
    tokens = (np.arange(payload_size(width, height) // 2) % 64000).astype("<u2")
    header = VideoHeader(7, 100, width, height, codec=CODEC, codec_profile=PROFILE)
    payload = tokens.tobytes()
    assert decode_video([header.encode(), payload]) == (header, payload)
    restored = unpack_tokens(payload, width, height)
    assert restored.shape == token_shape(width, height)
    np.testing.assert_array_equal(restored.ravel(), tokens)
    for bad in (payload[:-2], payload + b"\0\0"):
        with pytest.raises(ValueError, match="payload"):
            decode_video([header.encode(), bad])
    with pytest.raises(ValueError, match="index"):
        unpack_tokens(b"\xff\xff" + payload[2:], width, height)
    for bad in (
        replace(header, codec_profile=""),
        replace(header, codec_profile="other-model"),
        replace(header, width=960, height=540),
        replace(header, codec="h264"),
    ):
        with pytest.raises(ValueError):
            decode_video([bad.encode(), payload])


def test_capture_rejects_unsupported_tokenizer_resolution():
    from telesurgery.nodes.camera_settings import select

    camera = {"codecs": [CODEC], "width": 640, "height": 480}
    with pytest.raises(ValueError, match="1280x720"):
        select(camera, {"codec": CODEC})
