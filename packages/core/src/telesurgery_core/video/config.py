# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Video session configuration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    source: str = "synthetic"
    width: int = 1920
    height: int = 1080
    fps: float = 30
    pixel_format: str = ""
    codec: str = "h264"
    codec_gpu: int = 0
    rate_control: str = "cbr"
    bitrate_mbps: float = 0  # 0 selects an average for the resolution (encoder_settings).
    qp: int = 24
    jpeg_quality: int = 85
    encoder_preset: str = "P1"
    encoder_extra: str = ""
    hololink: str = "192.168.0.2"
    expander: int = 0
    skip_reset: bool = False
    receiver: str = "auto"
    depth: bool = False
    realsense_serial: str = ""
    max_bitrate_mbps: float = 0  # VBR only. 0 uses twice the resolved average.
