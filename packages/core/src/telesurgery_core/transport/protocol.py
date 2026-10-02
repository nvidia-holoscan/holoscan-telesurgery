# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Versioned, bounded wire messages. Network input is never unpickled."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

VERSION = 1
MAX_HEADER = 4096
MAX_VIDEO = 8 * 1024 * 1024
MAX_PIXELS = 4096 * 2160
MAX_RAW_VIDEO = MAX_PIXELS * 3


def _document(data: bytes) -> dict:
    if len(data) > MAX_HEADER:
        raise ValueError("message header is too large")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid JSON header") from exc
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        raise ValueError("missing protocol version")
    if value["version"] != VERSION:
        raise ValueError("unsupported protocol version")
    return value


def _integer(value: object, name: str, low: int, high: int = 2**63 - 1) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class VideoHeader:
    sequence: int
    captured_ns: int
    width: int
    height: int
    version: int = VERSION
    encode_ns: int = 0
    sim_command_sequence: int = -1
    codec: str = "h264"
    acquisition_ns: int = 0
    encoder_queue_ns: int = 0
    source_started_ns: int = 0  # Monotonic; only interpreted by processes on the source host.
    encoded_ns: int = 0
    pack_ns: int = 0

    def encode(self) -> bytes:
        return json.dumps(asdict(self), allow_nan=False, separators=(",", ":")).encode()

    @classmethod
    def decode(cls, data: bytes) -> VideoHeader:
        doc = _document(data)
        codec = doc.get("codec", "h264")
        if not isinstance(codec, str) or codec not in {"h264", "h265", "nvjpeg", "raw-bgr8"}:
            raise ValueError("unsupported video codec")
        width = _integer(doc.get("width"), "width", 1, 4096)
        height = _integer(doc.get("height"), "height", 1, 2160)
        return cls(
            _integer(doc.get("sequence"), "sequence", 0),
            _integer(doc.get("captured_ns"), "capture timestamp", 1),
            width,
            height,
            encode_ns=_integer(doc.get("encode_ns", 0), "encode duration", 0),
            sim_command_sequence=_integer(
                doc.get("sim_command_sequence", -1), "simulator command sequence", -1
            ),
            codec=codec,
            acquisition_ns=_integer(doc.get("acquisition_ns", 0), "acquisition duration", 0),
            encoder_queue_ns=_integer(doc.get("encoder_queue_ns", 0), "encoder queue duration", 0),
            source_started_ns=_integer(doc.get("source_started_ns", 0), "source start", 0),
            encoded_ns=_integer(doc.get("encoded_ns", 0), "encode completion", 0),
            pack_ns=_integer(doc.get("pack_ns", 0), "packing duration", 0),
        )


def decode_video(parts: list[bytes]) -> tuple[VideoHeader, bytes]:
    if len(parts) != 2:
        raise ValueError("expected a header and a bounded video payload")
    header = VideoHeader.decode(parts[0])
    size = len(parts[1])
    if header.codec == "raw-bgr8":
        if size != header.width * header.height * 3:
            raise ValueError("expected an exact raw BGR8 frame")
    elif not 0 < size <= MAX_VIDEO:
        raise ValueError("expected a bounded compressed video payload")
    return header, parts[1]
