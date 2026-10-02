# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json

import pytest
from telesurgery_core.transport.protocol import VideoHeader, decode_video


@pytest.mark.parametrize("codec", ["h264", "h265", "nvjpeg"])
def test_wire_round_trip(codec):
    header = VideoHeader(10, 2000, 640, 480, codec=codec)
    assert decode_video([header.encode(), b"h264"])[0] == header


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", 2),
        ("sequence", True),
        ("sequence", -1),
        ("captured_ns", 0),
        ("width", 10000),
        ("height", -1),
        ("encode_ns", -1),
        ("pack_ns", -1),
        ("acquisition_ns", -1),
        ("encoder_queue_ns", True),
        ("codec", ["h264"]),
        ("codec", "unknown"),
        ("sim_command_sequence", "x"),
    ],
)
def test_invalid_headers(key, value):
    doc = json.loads(VideoHeader(1, 100, 640, 480).encode())
    doc[key] = value
    with pytest.raises(ValueError):
        VideoHeader.decode(json.dumps(doc).encode())


@pytest.mark.parametrize("data", [b"\xff", b"[]", b"{}", b"x" * 4097])
def test_malformed_header(data):
    with pytest.raises(ValueError):
        VideoHeader.decode(data)


def test_wrong_parts():
    with pytest.raises(ValueError):
        decode_video([b"missing payload"])
