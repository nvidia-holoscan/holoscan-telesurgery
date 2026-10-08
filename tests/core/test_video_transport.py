# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import time
import uuid

import numpy as np
import pytest
import zmq
from telesurgery_core.transport import zmq as transport
from telesurgery_core.transport.protocol import VideoHeader, decode_video
from telesurgery_core.video.capture import Capture
from telesurgery_core.video.formats import decode_raw, encode_raw
from telesurgery_core.video.model import Frame


def test_synthetic_raw_gateway_round_trip():
    capture = Capture("synthetic", 320, 240)
    pixels = capture.read()
    header = VideoHeader(3, 100, 320, 240, sim_command_sequence=2)
    encoded = encode_raw(Frame(header, pixels))
    decoded = decode_raw(*encoded)
    np.testing.assert_array_equal(decoded.image, pixels)
    with pytest.raises(ValueError):
        decode_raw(encoded[0], b"truncated")
    capture.close()


def test_real_zmq_video_transport_and_empty_poll():
    endpoint = f"inproc://telesurgery-{uuid.uuid4().hex}"
    pub = transport.open_socket(zmq.PUB, endpoint, bind=True)
    sub = transport.open_socket(zmq.SUB, endpoint, bind=False)
    try:
        assert transport.latest(sub) is None
        header = VideoHeader(1, 1, 8, 8)
        deadline = time.monotonic() + 2
        packet = None
        while time.monotonic() < deadline and packet is None:
            pub.send_multipart([header.encode(), b"jpeg"])
            time.sleep(0.01)
            packet = transport.latest(sub)
        assert decode_video(packet) == (header, b"jpeg")
    finally:
        sub.close()
        pub.close()


def test_gateway_capture_preserves_upstream_timestamp():
    import socket

    with socket.socket() as free_port:
        free_port.bind(("127.0.0.1", 0))
        port = free_port.getsockname()[1]
    endpoint = f"tcp://127.0.0.1:{port}"
    publisher = transport.open_socket(zmq.PUB, endpoint, bind=True)
    capture = Capture(f"gateway:{endpoint}", 64, 48)
    header = VideoHeader(1, 123456, 64, 48, sim_command_sequence=7)
    header, data = encode_raw(Frame(header, np.full((48, 64, 3), 100, np.uint8)))
    try:
        deadline = time.monotonic() + 2
        image = None
        while image is None and time.monotonic() < deadline:
            publisher.send_multipart([header.encode(), data])
            time.sleep(0.01)
            image = capture.read()
        assert image.shape == (48, 64, 3)
        assert capture.last_capture_ns == 123456
        assert capture.last_header.sim_command_sequence == 7
    finally:
        capture.close()
        publisher.close()
