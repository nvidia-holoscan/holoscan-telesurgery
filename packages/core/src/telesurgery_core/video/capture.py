# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Synthetic scene and raw simulator capture."""

from __future__ import annotations

import cv2
import numpy as np
from telesurgery_core.transport.protocol import MAX_FRAME
from telesurgery_core.video import depth
from telesurgery_core.video.formats import decode_raw


class Capture:
    def __init__(self, source: str, width: int, height: int):
        self.width, self.height = width, height
        self.gateway = None
        self.last_capture_ns = None
        self.last_header = None
        self.depth = None
        self.background = None
        if source.startswith("gateway:"):
            import zmq
            from telesurgery_core.transport.zmq import open_socket

            self.gateway = open_socket(zmq.SUB, source[8:], bind=False, max_size=MAX_FRAME)
        elif source != "synthetic":
            raise ValueError(f"unsupported capture source: {source}")

    def read(self) -> np.ndarray | None:
        if self.gateway is not None:
            from telesurgery_core.transport.protocol import decode_video
            from telesurgery_core.transport.zmq import latest

            packet = latest(self.gateway)
            if packet is None:
                return None
            header, data = decode_video(packet)
            if (header.width, header.height) != (self.width, self.height):
                return None  # Discard queued frames from the previous simulator mode.
            self.last_capture_ns = header.captured_ns
            self.last_header = header
            color, packed = depth.split(header, data)
            self.depth = depth.unpack(header, packed)
            frame = decode_raw(header, color)
            return frame.image
        if self.background is None:
            image = np.full((self.height, self.width, 3), (35, 24, 20), dtype=np.uint8)
            center = (self.width // 2, self.height // 2)
            cv2.ellipse(
                image, center, (self.width // 3, self.height // 3), 0, 0, 360, (95, 90, 155), -1
            )
            for offset in range(-2, 3):
                px = center[0] + offset * self.width // 20
                cv2.line(image, (px, center[1] - 20), (px + 12, center[1] + 20), (180, 190, 200), 2)
            self.background = image
        image = self.background.copy()
        center = (self.width // 2, self.height // 2)
        tip = (self.width // 2, self.height // 2)
        cv2.line(image, (0, self.height), tip, (185, 195, 195), 12)
        cv2.circle(image, tip, 8, (70, 230, 110), 2)
        cv2.line(image, (self.width, self.height), (center[0] + 90, center[1]), (140, 150, 150), 10)
        cv2.putText(
            image,
            "SYNTHETIC TEST PATTERN",
            (15, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (220, 230, 230),
            1,
            cv2.LINE_AA,
        )
        return image

    def close(self) -> None:
        if self.gateway is not None:
            self.gateway.close()
            self.gateway = None
