# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Owned local video frames and timing metadata."""

from __future__ import annotations

from dataclasses import dataclass

from telesurgery_core.transport.protocol import VideoHeader


@dataclass
class Frame:
    header: VideoHeader
    image: object  # BGR8 for capture/diagnostics; native decoding returns owned GPU RGB8.
    ready_ns: int = 0  # Local monotonic time; never compared between machines.
