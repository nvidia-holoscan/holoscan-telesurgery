# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""RealSense color/depth framesets, aligned with the device's calibration."""

import time
from functools import lru_cache

import numpy as np
from telesurgery_core.adapters.base import CameraSample


@lru_cache(maxsize=16)
def camera_info(serial):
    import pyrealsense2 as rs

    device = next(
        (
            device
            for device in rs.context().query_devices()
            if any(
                device.supports(key) and device.get_info(key) == serial
                for key in (rs.camera_info.serial_number, rs.camera_info.asic_serial_number)
            )
        ),
        None,
    )
    if device is None:
        raise RuntimeError("RealSense camera is disconnected")
    modes = set()
    for sensor in device.query_sensors():
        for profile in sensor.get_stream_profiles():
            if profile.stream_type() == rs.stream.depth and profile.format() == rs.format.z16:
                video = profile.as_video_stream_profile()
                modes.add((video.width(), video.height(), profile.fps()))
    return {"serial": device.get_info(rs.camera_info.serial_number), "modes": sorted(modes)}


def enrich(cameras):
    for camera in cameras:
        if "realsense" not in camera["name"].lower() or not camera.get("serial"):
            continue
        try:
            info = camera_info(camera["serial"])
        except (ImportError, RuntimeError):
            continue
        if info["modes"]:
            camera.update(
                realsense_serial=info["serial"],
                depth_supported=True,
                depth_source="measured",
                depth_fps=sorted({m[2] for m in info["modes"]}),
            )


class RealSenseCamera:
    def __init__(self, config):
        import pyrealsense2 as rs

        self.pipeline = rs.pipeline()
        selected = rs.config()
        selected.enable_device(config.realsense_serial)
        selected.enable_stream(
            rs.stream.color, config.width, config.height, rs.format.bgr8, int(config.fps)
        )
        choices = [m for m in camera_info(config.realsense_serial)["modes"] if m[2] == config.fps]
        if not choices:
            raise ValueError("Depth is unavailable at the selected frame rate")
        width, height, fps = min(
            choices, key=lambda m: abs(m[0] - config.width) + abs(m[1] - config.height)
        )
        selected.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        self.align = rs.align(rs.stream.color)
        self.profile = self.pipeline.start(selected)
        self.period_ms = 1000 / config.fps

    def read(self):
        frames = self.pipeline.poll_for_frames()
        started = time.monotonic_ns()
        if not frames:
            return None
        aligned = self.align.process(frames)
        color, depth = aligned.get_color_frame(), aligned.get_depth_frame()
        if not color:
            return None
        values = None
        if depth and abs(color.get_timestamp() - depth.get_timestamp()) <= self.period_ms:
            values = np.asarray(depth.get_data(), dtype=np.float32) * depth.get_units()
        return CameraSample(
            np.asanyarray(color.get_data()).copy(),
            time.time_ns(),
            started_ns=started,
            depth=values,
        )

    def close(self):
        self.pipeline.stop()
