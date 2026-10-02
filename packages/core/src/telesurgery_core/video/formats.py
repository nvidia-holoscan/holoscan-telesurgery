# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded raw frames and independent-frame bitstream validation."""

from __future__ import annotations

import re
from dataclasses import replace

import numpy as np
from telesurgery_core.transport.protocol import MAX_RAW_VIDEO, VideoHeader
from telesurgery_core.video.model import Frame


def encode_raw(frame: Frame) -> tuple[VideoHeader, bytes]:
    """Lossless packed BGR8 for transport or the local simulator handoff."""
    image = np.asarray(frame.image)
    if (
        not 1 <= frame.header.width <= 4096
        or not 1 <= frame.header.height <= 2160
        or image.dtype != np.uint8
        or image.shape != (frame.header.height, frame.header.width, 3)
    ):
        raise ValueError("raw stream expects BGR8 matching the header")
    data = image.tobytes()
    if not 0 < len(data) <= MAX_RAW_VIDEO:
        raise ValueError("raw frame exceeds the size limit")
    return replace(frame.header, codec="raw-bgr8"), data


def decode_raw(header: VideoHeader, data: bytes) -> Frame:
    if (
        header.codec != "raw-bgr8"
        or not 0 < len(data) <= MAX_RAW_VIDEO
        or len(data) != header.width * header.height * 3
    ):
        raise ValueError("expected an exact raw BGR8 frame")
    image = np.frombuffer(data, dtype=np.uint8).reshape(header.height, header.width, 3)
    return Frame(header, image)


class _Bits:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def read(self, count=1):
        if self.offset + count > len(self.data) * 8:
            raise ValueError("truncated H.264 SPS")
        value = 0
        for _ in range(count):
            value = (value << 1) | ((self.data[self.offset // 8] >> (7 - self.offset % 8)) & 1)
            self.offset += 1
        return value

    def ue(self):
        zeros = 0
        while not self.read():
            zeros += 1
            if zeros > 31:
                raise ValueError("invalid H.264 exponential-Golomb field")
        return (1 << zeros) - 1 + self.read(zeros)


def h264_dimensions(data: bytes) -> tuple[int, int]:
    """Validate our progressive 8-bit 4:2:0 all-IDR contract before NVDEC allocation.

    Reject other profiles, predicted slices and interlaced streams: this is the
    application's wire format, not a general-purpose H.264 file parser.
    """
    if not data.startswith((b"\x00\x00\x01", b"\x00\x00\x00\x01")):
        raise ValueError("expected Annex B H.264")
    units = [unit for unit in re.split(b"\x00\x00\x00?\x01", data) if unit]
    kinds = [unit[0] & 31 for unit in units]
    if not {5, 7, 8}.issubset(kinds) or any(k not in {5, 6, 7, 8, 9, 12} for k in kinds):
        raise ValueError("H.264 requires SPS, PPS and IDR without predicted slices")
    if kinds.count(7) != 1 or kinds.count(8) != 1:
        raise ValueError("expected one H.264 parameter-set pair")
    sps = units[kinds.index(7)][1:]
    if len(sps) > 256:
        raise ValueError("oversized H.264 SPS")
    bits = _Bits(sps.replace(b"\x00\x00\x03", b"\x00\x00"))
    profile = bits.read(8)
    if profile not in {66, 77, 100}:
        raise ValueError("unsupported H.264 profile")
    bits.read(16)  # constraints and level
    bits.ue()  # SPS id
    if profile == 100:
        if bits.ue() != 1 or bits.ue() != 0 or bits.ue() != 0:
            raise ValueError("expected H.264 8-bit 4:2:0")
        bits.read()  # qpprime_y_zero_transform_bypass_flag
        if bits.read():
            raise ValueError("custom H.264 scaling matrices are unsupported")
    bits.ue()  # log2_max_frame_num_minus4
    poc = bits.ue()
    if poc == 0:
        bits.ue()
    elif poc != 2:
        raise ValueError("unsupported H.264 picture-order mode")
    bits.ue()  # max_num_ref_frames
    bits.read()  # gaps_in_frame_num_value_allowed_flag
    width, height = (bits.ue() + 1) * 16, (bits.ue() + 1) * 16
    if bits.read() != 1:
        raise ValueError("expected progressive H.264")
    bits.read()  # direct_8x8_inference_flag
    if bits.read():
        left, right, top, bottom = (bits.ue() for _ in range(4))
        width -= 2 * (left + right)
        height -= 2 * (top + bottom)
    if not 32 <= width <= 4096 or not 32 <= height <= 2160:
        raise ValueError("H.264 dimensions exceed the application limits")
    return width, height


def h265_dimensions(data: bytes) -> tuple[int, int]:
    """Validate our progressive Main/8-bit 4:2:0 HEVC all-IDR contract."""
    if not data.startswith((b"\x00\x00\x01", b"\x00\x00\x00\x01")):
        raise ValueError("expected Annex B H.265")
    units = [unit for unit in re.split(b"\x00\x00\x00?\x01", data) if unit]
    if any(len(unit) < 2 or unit[0] & 0x81 or unit[1] & 0xF8 or not unit[1] & 7 for unit in units):
        raise ValueError("invalid H.265 NAL header")
    kinds = [(unit[0] >> 1) & 63 for unit in units]
    if (
        not {32, 33, 34}.issubset(kinds)
        or not {19, 20}.intersection(kinds)
        or any(k not in {19, 20, 32, 33, 34, 35, 38, 39, 40} for k in kinds)
    ):
        raise ValueError("H.265 requires VPS, SPS, PPS and IDR without predicted slices")
    if any(kinds.count(kind) != 1 for kind in (32, 33, 34)):
        raise ValueError("expected one H.265 parameter-set group")
    sps = units[kinds.index(33)][2:]
    if len(sps) > 256:
        raise ValueError("oversized H.265 SPS")
    bits = _Bits(sps.replace(b"\x00\x00\x03", b"\x00\x00"))
    bits.read(4)
    layers = bits.read(3)
    bits.read()  # temporal_id_nesting_flag
    bits.read(3)
    if bits.read(5) != 1:
        raise ValueError("expected H.265 Main profile")
    bits.read(88)  # compatibility, constraints and level
    present = [(bits.read(), bits.read()) for _ in range(layers)]
    if layers:
        bits.read(2 * (8 - layers))
    for profile, level in present:
        if profile:
            bits.read(88)
        if level:
            bits.read(8)
    bits.ue()  # SPS id
    if bits.ue() != 1:
        raise ValueError("expected H.265 4:2:0")
    width, height = bits.ue(), bits.ue()
    if bits.read():
        left, right, top, bottom = (bits.ue() for _ in range(4))
        width -= 2 * (left + right)
        height -= 2 * (top + bottom)
    if bits.ue() or bits.ue():
        raise ValueError("expected H.265 8-bit pixels")
    if not 32 <= width <= 4096 or not 32 <= height <= 2160:
        raise ValueError("H.265 dimensions exceed the application limits")
    return width, height


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read baseline JPEG dimensions before allocating decoder output."""
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("expected a complete JPEG image")
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 255:
            break
        marker = data[offset + 1]
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if length < 2 or offset + length + 2 > len(data):
            break
        if marker == 0xC0:
            if length < 17 or data[offset + 4] != 8 or data[offset + 9] != 3:
                raise ValueError("expected baseline 8-bit color JPEG")
            height = int.from_bytes(data[offset + 5 : offset + 7], "big")
            width = int.from_bytes(data[offset + 7 : offset + 9], "big")
            if not 32 <= width <= 4096 or not 32 <= height <= 2160:
                raise ValueError("JPEG dimensions exceed the application limits")
            return width, height
        if marker == 0xDA:
            break
        offset += 2 + length
    raise ValueError("missing baseline JPEG frame header")


def dimensions(codec, data):
    return {"h264": h264_dimensions, "h265": h265_dimensions, "nvjpeg": jpeg_dimensions}[codec](
        data
    )
