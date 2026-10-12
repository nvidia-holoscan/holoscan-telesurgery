# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Only device-supported modes reach a worker; buffer timing excludes capture waits."""

import asyncio
import errno
import hashlib
import json
import struct
import sys
import time

import numpy as np
import pytest
from telesurgery.nodes.camera_settings import modes, select
from telesurgery_core.adapters import v4l2
from telesurgery_core.configuration import save
from telesurgery_core.video.config import Config


@pytest.mark.parametrize("capture, supported", [(False, True), (True, False), (True, True)])
def test_usb_probe_excludes_depth_and_metadata_and_preserves_product_name(
    tmp_path, monkeypatch, capture, supported
):
    device = tmp_path / "video0"
    device.touch()
    usb = tmp_path / "usb"
    (usb / "interface").mkdir(parents=True)
    name = "Intel(R) RealSense(TM) Depth Camera 455"
    (usb / "product").write_text(name)
    sysfs = tmp_path / "video4linux"
    (sysfs / "video0").mkdir(parents=True)
    (sysfs / "video0/device").symlink_to(usb / "interface")
    path = v4l2.Path
    monkeypatch.setattr(
        v4l2, "Path", lambda value: sysfs if value == "/sys/class/video4linux" else path(value)
    )

    def ioctl(fd, request, data):
        data[16:48] = name.encode()[:32]
        struct.pack_into("I", data, 84, 0x80000000)
        struct.pack_into("I", data, 88, 1 if capture else 0x00800000)

    mode = {"width": 1280, "height": 800, "pixel_format": "YUYV", "fps": [30]}
    monkeypatch.setattr(v4l2.fcntl, "ioctl", ioctl)
    monkeypatch.setattr(v4l2, "capture_modes", lambda fd: [mode] if supported else [])
    v4l2._probe.cache_clear()
    try:
        result = v4l2._probe(str(device), (0, 0, 0))
        if capture and supported:
            assert result["name"] == name
            assert result["modes"] == [mode]
        else:
            assert result is None
    finally:
        v4l2._probe.cache_clear()


@pytest.mark.parametrize("infrared_formats", [["GREY"], ["GREY", "UYVY"]])
def test_usb_discovery_excludes_monochrome_interfaces(tmp_path, monkeypatch, infrared_formats):
    devices = tmp_path / "dev"
    devices.mkdir()
    for index in range(2):
        (devices / f"video{index}").touch()
    path = v4l2.Path
    monkeypatch.setattr(
        v4l2,
        "Path",
        lambda value: devices if value == "/dev" else path(value),
    )

    def probe(device, identity):
        formats = ["YUYV"] if device.endswith("video0") else infrared_formats
        return {
            "name": "RealSense",
            "bus": "usb-1",
            "modes": [
                {"width": 1280, "height": 720, "pixel_format": fmt, "fps": [30]} for fmt in formats
            ],
        }

    monkeypatch.setattr(v4l2, "_probe", probe)
    cameras = v4l2.camera_devices()
    assert len(cameras) == 1
    assert cameras[0]["name"] == "RealSense"
    assert cameras[0]["source"] == f"v4l2:{devices / 'video0'}"


def test_usb_modes_keep_format_specific_frame_rates(monkeypatch):
    def ioctl(fd, request, data):
        index = struct.unpack_from("I", data)[0]
        if request == 0xC0405602:
            if index >= 2:
                raise OSError(errno.EINVAL, "End of formats")
            data[44:48] = (b"YUYV", b"MJPG")[index]
        elif request == 0xC02C564A:
            if index:
                raise OSError(errno.EINVAL, "End of sizes")
            struct.pack_into("3I", data, 8, 1, 1920, 1080)
        elif request == 0xC034564B:
            if index:
                raise OSError(errno.EINVAL, "End of rates")
            struct.pack_into("3I", data, 16, 1, 1, 60 if data[4:8] == b"MJPG" else 30)

    monkeypatch.setattr(v4l2.fcntl, "ioctl", ioctl)
    reported = v4l2.capture_modes(0)
    camera = {
        "source": "v4l2:fixture",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "pixel_format": "YUYV",
        "modes": reported,
    }
    with pytest.raises(ValueError, match="does not support"):
        select(camera, {"fps": 60})
    selected = select(camera, {"pixel_format": "MJPG", "fps": 60, "qp": 18, "encoder_preset": "P3"})
    assert Config(**selected).fps == 60
    assert selected["qp"] == 18
    for bad in (
        {"source": "elsewhere"},
        {"qp": -1},
        {"qp": 24.5},
        {"encoder_preset": "P99"},
    ):
        with pytest.raises(ValueError):
            select(camera, bad)


def test_only_available_codecs_are_offered_and_probed_once(monkeypatch):
    from telesurgery_core.video import capabilities

    calls = []

    def probe(config):
        calls.append(config.codec)
        if config.codec == "h265":
            raise RuntimeError("No HEVC encoder")

    capabilities.supported_codecs.cache_clear()
    monkeypatch.setattr(capabilities, "probe", probe)
    monkeypatch.setattr(capabilities.importlib.util, "find_spec", lambda _: None)
    try:
        assert capabilities.supported_codecs() == ["h264", "nvjpeg", "raw-bgr8"]
        assert capabilities.supported_codecs() == ["h264", "nvjpeg", "raw-bgr8"]
        assert calls == ["h264", "h265", "nvjpeg"]
        with pytest.raises(ValueError, match="does not support"):
            select({"codecs": capabilities.supported_codecs()}, {"codec": "h265"})
    finally:
        capabilities.supported_codecs.cache_clear()


def test_hsb_supported_resolutions_are_native_modes():
    camera = {"source": "imx274", "width": 1920, "height": 1080, "fps": 60}
    assert select(camera)["codec"] == "h264"
    assert {(m["width"], m["height"]) for m in modes(camera)} == {(1920, 1080), (3840, 2160)}
    assert select(camera, {"width": 3840, "height": 2160})["fps"] == 60
    for settings in ({"fps": 30}, {"width": 3840}, {"width": 1280, "height": 720}):
        with pytest.raises(ValueError):
            select(camera, settings)


def test_hsb_receiver_selection_matches_node_capabilities():
    camera = {
        "source": "imx274",
        "width": 1920,
        "height": 1080,
        "fps": 60,
        "receivers": ["fusa", "linux"],
    }
    assert select(camera)["receiver"] == "fusa"
    assert select(camera, {"receiver": "linux"})["receiver"] == "linux"
    camera["receivers"] = ["linux"]
    assert select(camera)["receiver"] == "linux"
    with pytest.raises(ValueError, match="HSB receiver"):
        select(camera, {"receiver": "fusa"})
    with pytest.raises(ValueError, match="only available for HSB"):
        select({"source": "v4l2:/dev/video0"}, {"receiver": "linux"})


def test_inventory_exposes_stream_choices_without_device_addresses(tmp_path):
    from telesurgery.server.application import Application

    app = Application("patient", tmp_path)
    camera = {
        "id": "camera",
        "name": "IMX274",
        "source": "imx274",
        "kind": "HSB",
        "width": 1920,
        "height": 1080,
        "fps": 60,
        "hololink": "192.168.0.2",
        "receivers": ["fusa", "linux"],
        "encoding_error": "Could not prepare tokenizer; continuing h264",
    }
    camera["modes"] = modes(camera)
    camera.update(select(camera))
    app.nodes = {"host": {"status": "online", "cameras": [camera]}}
    public = app.inventory()["cameras"][0]
    assert public["modes"] == camera["modes"]
    assert public["qp"] == 24
    assert public["encoder_preset"] == "P1"
    assert public["receiver"] == "fusa"
    assert public["receivers"] == ["fusa", "linux"]
    assert public["encoding_error"] == camera["encoding_error"]
    assert "source" not in public and "hololink" not in public


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_codec", ["surgical-tokenizer", "nvjpeg"])
async def test_failed_encoding_change_preserves_live_worker_and_clears_on_restart(
    tmp_path, monkeypatch, failed_codec
):
    from telesurgery.nodes import local

    create_process = asyncio.create_subprocess_exec

    async def worker(*args, **kwargs):
        return await create_process(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)

    monkeypatch.setattr(local.asyncio, "create_subprocess_exec", worker)
    node = local.LocalNode(tmp_path, None)
    node.cameras["sensor"] = {
        "id": "sensor",
        "name": "Camera",
        "source": "synthetic",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "codecs": ["h264", "surgical-tokenizer", "nvjpeg"],
    }
    slug = hashlib.sha256(b"sensor").hexdigest()[:12]
    error = local.Path(node.temp.name) / f"{slug}.error"
    error.write_text("Old startup error")
    try:
        await node.start_camera("sensor")
        assert not error.exists()
        active = node.workers["sensor"]
        active.update(updated=time.monotonic(), frames=1, active_codec="h264")
        await node.start_camera("sensor", {"codec": failed_codec})
        assert node.inventory()["cameras"][0]["codec"] == "h264"
        error.write_text(f"Could not prepare {failed_codec}; continuing h264")
        camera = node.inventory()["cameras"][0]
        assert camera["status"] == "live" and camera["error"] == ""
        assert camera["encoding_error"] == error.read_text()
        assert camera["codec"] == "h264"  # A failed native-only codec must not hide browser video.
        # Retry identical settings must notify the encoder without restarting capture.
        stamp = active["settings"].stat().st_mtime_ns
        await node.start_camera("sensor", {"codec": failed_codec})
        assert active["settings"].stat().st_mtime_ns != stamp
        await node.start_camera("sensor", {"codec": "h264"})
        assert node.workers["sensor"] is active
        assert active["process"].returncode is None
        assert json.loads(active["settings"].read_text())["camera"]["codec"] == "h264"
        await node.stop_camera("sensor")
        assert not error.exists()
        await node.start_camera("sensor")
        assert node.inventory()["cameras"][0]["encoding_error"] == ""
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_saved_camera_settings_survive_discovery_and_restart(tmp_path, monkeypatch):
    from telesurgery.nodes import local

    def discover(*args):
        return [
            {
                "id": "sensor",
                "name": "IMX274",
                "source": "imx274",
                "kind": "HSB",
                "width": 1920,
                "height": 1080,
                "fps": 60,
            }
        ], []

    monkeypatch.setattr(local, "discover", discover)
    monkeypatch.setattr(local, "supported_codecs", lambda: ["raw-bgr8", "h264", "h265", "nvjpeg"])
    save(tmp_path / "streams.yaml", {"sensor": {"width": 3840, "height": 2160}})
    node = local.LocalNode(tmp_path, None)
    try:
        for _ in range(2):
            await node.refresh()
            camera = node.inventory()["cameras"][0]
            assert (camera["width"], camera["height"]) == (3840, 2160)
            assert len(camera["modes"]) == 2
        # HSB announcements are intermittent. A retained camera keeps its codec choices.
        monkeypatch.setattr(local, "discover", lambda *args: ([], []))
        await node.refresh()
        camera = node.inventory()["cameras"][0]
        assert camera["codecs"] == ["raw-bgr8", "h264", "h265", "nvjpeg"]
        assert (camera["width"], camera["height"]) == (3840, 2160)
    finally:
        await node.close()


def test_usb_timer_starts_after_buffer_delivery(monkeypatch):
    from types import SimpleNamespace

    from telesurgery_core.adapters import cameras
    from telesurgery_runtime.application.video import Capture

    ticks = {"now": 1_000_000}

    def receive():
        ticks["now"] += 30_000_000  # Hardware read blocks for a frame.
        return True, np.zeros((32, 32, 3), np.uint8)

    monkeypatch.setattr(cameras.time, "monotonic_ns", lambda: ticks["now"])
    monkeypatch.setattr(cameras.time, "perf_counter_ns", lambda: ticks["now"] + 100)
    camera = cameras.UsbCamera.__new__(cameras.UsbCamera)
    camera.capture = SimpleNamespace(read=receive)
    camera.width = camera.height = 32
    frame = Capture(Config(), camera).compute()
    assert frame.header.source_started_ns == 31_000_000
    assert frame.header.acquisition_ns == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [0, 10])
async def test_camera_silence_stops_worker_and_reports_error(tmp_path, monkeypatch, frames):
    from telesurgery.nodes import local

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(10)",
        stdout=asyncio.subprocess.PIPE,
    )
    await asyncio.wait_for(process.stdout.readline(), 5)
    wait_for = asyncio.wait_for

    async def short_deadlines(awaitable, timeout):
        return await wait_for(awaitable, 0.02 if timeout in {30, 8} else timeout)

    monkeypatch.setattr(local.asyncio, "wait_for", short_deadlines)
    node = local.LocalNode(tmp_path, None)
    node.cameras["sensor"] = {"id": "sensor", "name": "Camera"}
    worker = {
        "process": process,
        "updated": 0,
        "frames": frames,
        "settings": tmp_path / "camera.json",
    }
    node.workers["sensor"] = worker
    try:
        await node._watch("sensor", worker, "sensor")
        camera = node.inventory()["cameras"][0]
        assert camera["status"] == "error"
        assert camera["error"] == "No camera frames received for 30 seconds. Check the camera logs."
        assert process.returncode == -9  # A hung driver's teardown cannot block the node.
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        node.workers.clear()
        await node.close()
