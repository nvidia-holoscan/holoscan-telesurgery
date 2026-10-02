# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read USB capture interfaces and modes without opening a video stream."""

import errno
import fcntl
import hashlib
import os
import struct
from collections import defaultdict
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from telesurgery_core.video.config import Config

# Formats that the OpenCV capture adapter converts to 8-bit BGR.
FORMATS = {"MJPG", "JPEG", "YUYV", "UYVY", "NV12", "YU12", "YV12", "RGB3", "BGR3", "GREY"}


def _enumerate(fd, request, size, *fields):
    index = 0
    while True:
        data = bytearray(size)
        struct.pack_into(f"{len(fields) + 1}I", data, 0, index, *fields)
        try:
            fcntl.ioctl(fd, request, data)
        except OSError as exc:
            if exc.errno == errno.EINVAL:
                return
            raise
        yield data
        index += 1


def _sizes(data):
    kind = struct.unpack_from("I", data, 8)[0]
    if kind == 1:
        return [struct.unpack_from("2I", data, 12)]
    low_w, high_w, step_w, low_h, high_h, step_h = struct.unpack_from("6I", data, 12)
    # Continuous devices have infinitely many choices; offer common sizes and bounds.
    candidates = {
        (low_w, low_h),
        (high_w, high_h),
        (640, 480),
        (1280, 720),
        (1920, 1080),
        (2560, 1440),
        (3840, 2160),
    }
    return sorted(
        (w, h)
        for w, h in candidates
        if low_w <= w <= high_w
        and low_h <= h <= high_h
        and (w - low_w) % max(1, step_w) == 0
        and (h - low_h) % max(1, step_h) == 0
    )


def _rates(data):
    kind, numerator, denominator = struct.unpack_from("3I", data, 16)
    if not numerator or not denominator:
        return []
    minimum = Fraction(numerator, denominator)
    if kind == 1:
        return [float(1 / minimum)]
    maximum = Fraction(*struct.unpack_from("2I", data, 28))
    step_n, step_d = struct.unpack_from("2I", data, 36)
    step = Fraction(step_n, step_d) if step_n and step_d else 0
    candidates = {
        minimum,
        maximum,
        *(Fraction(1, fps) for fps in (5, 10, 15, 24, 25, 30, 50, 60, 90, 120)),
    }
    return [
        float(1 / value)
        for value in candidates
        if minimum <= value <= maximum and (not step or ((value - minimum) / step).denominator == 1)
    ]


def capture_modes(fd):
    modes = []
    for fmt in _enumerate(fd, 0xC0405602, 64, 1):  # VIDIOC_ENUM_FMT, VIDEO_CAPTURE
        fourcc = struct.unpack_from("I", fmt, 44)[0]
        name = bytes(fmt[44:48]).decode("ascii", errors="replace")
        if name not in FORMATS:
            continue
        for size in _enumerate(fd, 0xC02C564A, 44, fourcc):  # VIDIOC_ENUM_FRAMESIZES
            for width, height in _sizes(size):
                if (
                    min(width, height) < 32
                    or width > 4096
                    or height > 2160
                    or width % 2
                    or height % 2
                ):
                    continue  # The streaming encoder requires even dimensions.
                rates = set()
                for interval in _enumerate(fd, 0xC034564B, 52, fourcc, width, height):
                    rates.update(_rates(interval))
                if rates:
                    modes.append(
                        {
                            "width": width,
                            "height": height,
                            "pixel_format": name,
                            "fps": sorted(rates, reverse=True),
                        }
                    )
    return modes


@lru_cache(maxsize=64)
def _probe(path, identity):
    # Device inode/ctime invalidates cached capabilities after unplug/replug.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        data = bytearray(104)
        fcntl.ioctl(fd, 0x80685600, data)  # VIDIOC_QUERYCAP
        caps = struct.unpack_from("I", data, 84)[0]
        if caps & 0x80000000:
            caps = struct.unpack_from("I", data, 88)[0]
        if not caps & 1:
            return None  # Exclude metadata-only interfaces.
        return {
            "name": bytes(data[16:48]).split(b"\0", 1)[0].decode(errors="replace"),
            "bus": bytes(data[48:80]).split(b"\0", 1)[0].decode(errors="replace"),
            "modes": capture_modes(fd),
        }
    finally:
        os.close(fd)


def camera_devices():
    cameras = []
    for device in sorted(Path("/dev").glob("video*")):
        try:
            info = device.stat()
            probe = _probe(str(device), (info.st_rdev, info.st_ino, info.st_ctime_ns))
            if not probe:
                continue
            paths = sorted(p for p in Path("/dev/v4l/by-id").glob("*") if p.resolve() == device)
            path = str(paths[0]) if paths else str(device)
            modes = probe["modes"]
            choices = [(m, fps) for m in modes for fps in m["fps"]]
            mode, fps = (
                min(
                    choices,
                    key=lambda pair: (
                        abs(pair[0]["width"] - Config.width)
                        + abs(pair[0]["height"] - Config.height),
                        pair[0]["pixel_format"] in {"MJPG", "JPEG"},
                        abs(pair[1] - Config.fps),
                    ),
                )
                if choices
                else (
                    {"width": Config.width, "height": Config.height, "pixel_format": ""},
                    Config.fps,
                )
            )
            cameras.append(
                {
                    **probe,
                    **mode,
                    "fps": fps,
                    "id": "usb-" + hashlib.sha256(path.encode()).hexdigest()[:12],
                    "source": f"v4l2:{path}",
                    "kind": "USB",
                }
            )
        except (OSError, ValueError):
            continue
    groups = defaultdict(list)
    for camera in cameras:
        groups[camera["name"], camera["bus"]].append(camera)
    for siblings in groups.values():
        if len(siblings) < 2:
            continue
        labels = [
            "Monochrome"
            if c["modes"] and all(m["pixel_format"] == "GREY" for m in c["modes"])
            else "Color"
            for c in siblings
        ]
        for index, (camera, label) in enumerate(zip(siblings, labels, strict=True)):
            suffix = f" {index + 1}" if labels.count(label) > 1 else ""
            camera["name"] += f" · {label}{suffix}"
    return cameras
