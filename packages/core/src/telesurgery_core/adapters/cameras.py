# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Camera factories; adding a device does not change the streaming graphs."""

from __future__ import annotations

import time

from telesurgery_core.adapters.base import CameraSample
from telesurgery_core.video.capture import Capture


class SoftwareCamera:
    """Synthetic scene or raw simulator frames."""

    def __init__(self, config):
        self.capture = Capture(config.source, config.width, config.height)

    def read(self):
        image = self.capture.read()
        started = time.monotonic_ns()
        if image is None:
            return None
        upstream = self.capture.last_header
        return CameraSample(
            image,
            self.capture.last_capture_ns or time.time_ns(),
            sim_command_sequence=upstream.sim_command_sequence if upstream else -1,
            started_ns=(upstream.source_started_ns or -1) if upstream else started,
            depth=self.capture.depth,
        )

    def close(self):
        self.capture.close()


class UsbCamera:
    def __init__(self, config):
        import cv2

        self.capture = cv2.VideoCapture(config.source.removeprefix("v4l2:"), cv2.CAP_V4L2)
        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open camera {config.source}")
        # One buffer starves UVC capture while OpenCV owns it, halving the frame rate.
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        if config.pixel_format:
            self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.pixel_format))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, config.width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, config.height)
        self.capture.set(cv2.CAP_PROP_FPS, config.fps)
        if config.pixel_format:
            actual = (
                round(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                round(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                self.capture.get(cv2.CAP_PROP_FPS),
                int(self.capture.get(cv2.CAP_PROP_FOURCC))
                .to_bytes(4, "little")
                .decode("ascii", errors="replace"),
            )
            if (
                actual[:2] != (config.width, config.height)
                or abs(actual[2] - config.fps) > 0.05
                or actual[3] != config.pixel_format
            ):
                self.capture.release()
                raise RuntimeError(
                    f"Camera rejected requested mode; negotiated {actual[0]} × {actual[1]} "
                    f"at {actual[2]:g} FPS ({actual[3]})"
                )
        self.width, self.height = config.width, config.height

    def read(self):
        ok, image = self.capture.read()
        started = time.monotonic_ns()
        if not ok:
            return None
        import cv2

        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[:2] != (self.height, self.width):
            image = cv2.resize(image, (self.width, self.height))
        return CameraSample(image, time.time_ns(), started_ns=started)

    def close(self):
        self.capture.release()


def open_camera(config):
    if config.depth and config.realsense_serial:
        from telesurgery_core.adapters.realsense import RealSenseCamera

        return RealSenseCamera(config)
    if config.source.startswith("v4l2:"):
        return UsbCamera(config)
    return SoftwareCamera(config)
