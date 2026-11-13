# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""IPPP framing, wire format and loss detection, independent of any GPU."""

import json

import pytest
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.formats import video_frame
from telesurgery_core.video.reference import ReferenceChain

START = b"\x00\x00\x00\x01"


def frame(gop, index):
    return VideoHeader(1, 1, 64, 64, keyframe=index == 0, gop=gop, gop_index=index)


def test_wire_format_carries_gop_position_and_defaults_to_keyframes():
    header = frame(7, 3)
    assert VideoHeader.decode(header.encode()) == header
    # A node predating IPPP sends none of these fields: every frame stands alone.
    legacy = json.loads(VideoHeader(1, 1, 64, 64).encode())
    for name in ("keyframe", "gop", "gop_index"):
        del legacy[name]
    assert VideoHeader.decode(json.dumps(legacy).encode()).keyframe is True


@pytest.mark.parametrize("key,value", [("keyframe", 1), ("gop", -1), ("gop_index", "1")])
def test_invalid_framing_is_rejected(key, value):
    doc = json.loads(frame(1, 0).encode())
    doc[key] = value
    with pytest.raises(ValueError):
        VideoHeader.decode(json.dumps(doc).encode())


def test_chain_accepts_consecutive_deltas_and_rejects_every_gap():
    chain = ReferenceChain()
    assert not chain.accept(frame(1, 1))  # Joined mid-GOP.
    assert chain.accept(frame(1, 0))
    assert chain.accept(frame(1, 1)) and chain.accept(frame(1, 2))
    assert not chain.accept(frame(1, 4))  # Frame 3 was dropped...
    assert not chain.accept(frame(1, 5))  # ...so nothing decodes until an IDR.
    assert chain.accept(frame(2, 0))
    assert not chain.accept(frame(1, 1))  # An old GOP never mixes with the new one.
    assert not chain.accept(frame(2, 1))  # The rejection above discarded the chain.


def test_keyframe_requests_are_paced():
    now = [0.0]
    chain = ReferenceChain(interval=0.5, clock=lambda: now[0])
    assert chain.refresh_due()
    assert not chain.refresh_due()
    now[0] = 0.49
    assert not chain.refresh_due()
    now[0] = 0.5
    assert chain.refresh_due()


H264_IDR = START + b"\x67\x42\x00\x1e" + START + b"\x68\xce" + START + b"\x65\x88"
H265_DELTA = START + b"\x02\x01\xaf"  # TRAIL_R


def test_delta_frames_are_validated_without_parameter_sets():
    assert video_frame("h264", START + b"\x41\x9a") == (None, False)
    assert video_frame("h265", H265_DELTA) == (None, False)
    for codec, bad in (
        ("h264", START + b"\x67\x42\x00\x1e" + START + b"\x41\x9a"),  # Parameter sets mid-GOP
        ("h264", START + b"\x06\x05"),  # No slice at all
        ("h265", START + b"\x40\x01\x0c"),  # VPS only
    ):
        with pytest.raises(ValueError):
            video_frame(codec, bad)
    with pytest.raises(ValueError, match="Annex B"):
        video_frame("h264", b"\x41\x9a")


def test_keyframes_still_require_the_full_contract():
    with pytest.raises(ValueError):
        video_frame("h264", H264_IDR)  # Truncated SPS
