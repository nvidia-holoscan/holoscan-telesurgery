# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Device-side UVC zoom; changing this control does not reconfigure capture."""

import errno
import fcntl
import os
import struct

ZOOM_ABSOLUTE = 0x009A090D


def query(fd):
    data = bytearray(68)
    struct.pack_into("I", data, 0, ZOOM_ABSOLUTE)
    try:
        fcntl.ioctl(fd, 0xC0445624, data)  # VIDIOC_QUERYCTRL
    except OSError as exc:
        if exc.errno in {errno.EINVAL, errno.ENOTTY}:
            return None
        raise
    minimum, maximum, step, default, flags = struct.unpack_from("4iI", data, 40)
    # Disabled, grabbed, read-only, inactive or write-only controls cannot offer
    # a reliable interactive slider. A zoom control does not imply optical zoom.
    if flags & (1 | 2 | 4 | 16 | 64) or step <= 0 or maximum <= minimum:
        return None
    value = bytearray(struct.pack("Ii", ZOOM_ABSOLUTE, 0))
    fcntl.ioctl(fd, 0xC008561B, value)  # VIDIOC_G_CTRL
    return {
        "min": minimum,
        "max": maximum,
        "step": step,
        "default": default,
        "value": struct.unpack_from("i", value, 4)[0],
    }


def read(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            return query(fd)
        finally:
            os.close(fd)
    except OSError:
        return None


def set_value(source, value):
    if not source.startswith("v4l2:"):
        raise ValueError("This camera does not expose camera zoom")
    fd = os.open(source.removeprefix("v4l2:"), os.O_RDWR | os.O_NONBLOCK)
    try:
        control = query(fd)
        if control is None:
            raise ValueError("Camera zoom is unavailable")
        if (
            type(value) is not int
            or not control["min"] <= value <= control["max"]
            or (value - control["min"]) % control["step"]
        ):
            raise ValueError("Camera zoom is outside the device's supported range")
        fcntl.ioctl(fd, 0xC008561C, bytearray(struct.pack("Ii", ZOOM_ABSOLUTE, value)))
        return query(fd)
    finally:
        os.close(fd)
