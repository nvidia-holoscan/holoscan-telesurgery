# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Real NVIDIA codec tests; these never substitute a software encoder/decoder."""

import contextlib
import os
import subprocess
import sys
import time
from dataclasses import replace

import numpy as np
import pytest
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.codecs import GpuCodec, create_codec
from telesurgery_core.video.config import Config
from telesurgery_core.video.formats import dimensions, h264_dimensions, h265_dimensions
from telesurgery_core.video.model import Frame

pytestmark = pytest.mark.gpu


def test_jpeg_first_use_loads_only_required_plugins():
    # Import diagnostics happen only once per process, before an encoder exists.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
from pathlib import Path
from telesurgery_core.video.codecs import probe
from telesurgery_core.video.config import Config

assert probe(Config(codec="nvjpeg"))["round_trip"] == "passed"
assert os.environ["NVIMGCODEC_EXTENSIONS_PATH"] == "previous-extension-path"
libraries = Path("/proc/self/maps").read_text()
assert "libnvjpeg_ext.so" in libraries
assert "libnvjpeg2k_ext.so" not in libraries
assert "libnvtiff_ext.so" not in libraries
""",
        ],
        env={**os.environ, "NVIMGCODEC_EXTENSIONS_PATH": "previous-extension-path"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "nvjpeg2k" not in output.lower(), output
    assert "nvtiff" not in output.lower(), output


@pytest.mark.parametrize("codec", ["h264", "h265", "nvjpeg"])
def test_gpu_colors_timestamps_loss_late_join_and_restart(codec):
    config = Config(codec=codec, qp=18)
    with contextlib.ExitStack() as stack:
        encoder = GpuCodec(config, encode=True)
        stack.callback(encoder.close)
        packets, originals = [], {}
        # Patches reveal RGB/BGR and full/limited-range mistakes. Different
        # input frames expose buffering and incorrect metadata pairing.
        for sequence in range(12):
            pixels = np.zeros((240, 320, 3), np.uint8)
            pixels[:, :160] = (10 + sequence * 6, 60, 180)
            pixels[:, 160:] = (180, 100, 20 + sequence * 6)
            header = VideoHeader(sequence, time.time_ns(), 320, 240, sim_command_sequence=sequence)
            originals[sequence] = (header, pixels)
            ready = time.perf_counter_ns() - 1_000_000
            packet = encoder.encode(Frame(header, pixels, ready_ns=ready))
            # Regression: first input must return its own packet immediately.
            assert packet is not None
            assert packet[0].sequence == sequence
            packets.append(packet)
        assert len(packets) == 12
        for header, data in packets:
            assert dimensions(codec, data) == (320, 240)
            assert header.captured_ns == originals[header.sequence][0].captured_ns
            assert header.encode_ns > 0
            assert header.encoder_queue_ns >= 1_000_000
        # A fresh decoder joins halfway through, skips frames, then sees an
        # earlier independent frame as on a publisher restart. No reference wait.
        decoder = GpuCodec(config, encode=False)
        stack.callback(decoder.close)
        held_frames = []
        for header, data in (packets[3], packets[7], packets[0]):
            frame = decoder.decode(header, data)
            expected = originals[header.sequence][1]
            assert np.abs(frame.image.astype(float) - expected).mean() < 4
            assert frame.header.sim_command_sequence == header.sequence
            held_frames.append((frame, frame.image.copy()))
        # The pinned pool must not overwrite frames still owned by the viewer.
        for held, saved in held_frames:
            np.testing.assert_array_equal(held.image, saved)
        with pytest.raises(ValueError, match="bounded header"):
            decoder.decode(replace(packets[0][0], width=160), packets[0][1])
        with pytest.raises(RuntimeError, match="codec mismatch"):
            decoder.decode(replace(packets[0][0], codec="raw-bgr8"), packets[0][1])
        with pytest.raises(ValueError):
            decoder.decode(packets[0][0], b"not a compressed frame")


def test_h264_rejects_dependent_slices_and_truncated_sps():
    config = Config(codec="h264")
    encoder = GpuCodec(config, encode=True)
    try:
        header = VideoHeader(0, 1, 320, 240)
        packet = encoder.encode(Frame(header, np.zeros((240, 320, 3), np.uint8)))
        header, data = packet
        with pytest.raises(ValueError, match="predicted"):
            h264_dimensions(data + b"\x00\x00\x01\x41\x80")
        with pytest.raises(ValueError):
            h264_dimensions(data[:10])
    finally:
        encoder.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (3840, 2160)])
@pytest.mark.parametrize("codec", ["h264", "h265", "nvjpeg", "raw-bgr8"])
def test_native_camera_resolutions_and_gpu_input(width, height, codec):
    import cupy as cp

    config = Config(codec=codec, qp=18)
    with contextlib.ExitStack() as stack:
        encoder = create_codec(config, encode=True)
        stack.callback(encoder.close)
        decoder = create_codec(config, encode=False)
        stack.callback(decoder.close)
        pixels = cp.empty((height, width, 3), dtype=cp.uint8)
        pixels[:] = cp.asarray([30, 90, 170], dtype=cp.uint8)
        cp.cuda.get_current_stream().synchronize()
        header = VideoHeader(0, 1, width, height)
        frame = decoder.decode(*encoder.encode(Frame(header, pixels)))
        assert frame.image.shape == (height, width, 3)
        np.testing.assert_allclose(frame.image[height // 2, width // 2], [30, 90, 170], atol=4)


def test_h265_rejects_dependent_slices_and_truncated_sps():
    encoder = GpuCodec(Config(codec="h265"), encode=True)
    try:
        _, data = encoder.encode(
            Frame(VideoHeader(0, 1, 320, 240), np.zeros((240, 320, 3), np.uint8))
        )
        with pytest.raises(ValueError, match="predicted"):
            h265_dimensions(data + b"\x00\x00\x01\x02\x01\x80")
        with pytest.raises(ValueError):
            h265_dimensions(data[:10])
    finally:
        encoder.close()


def test_native_decoder_follows_patient_codec_changes():
    from dataclasses import asdict

    from telesurgery_runtime.viewer import ReceiveDecode

    viewer = ReceiveDecode()
    viewer.start()
    try:
        for codec in ("h264", "raw-bgr8", "h265", "nvjpeg", "raw-bgr8", "h264"):
            encoder = create_codec(Config(codec=codec), encode=True)
            try:
                pixels = np.full((240, 320, 3), [20, 90, 170], dtype=np.uint8)
                header, data = encoder.encode(
                    Frame(VideoHeader(0, time.time_ns(), 320, 240), pixels)
                )
                viewer.put(asdict(header), data)
                rgb = viewer.compute()
                assert viewer.codec == codec
                np.testing.assert_allclose(rgb[120, 160].get(), [170, 90, 20], atol=4)
            finally:
                encoder.close()
    finally:
        viewer.stop()


def test_h264_rejects_stock_binding(monkeypatch):
    import PyNvVideoCodec as nvc

    monkeypatch.delattr(nvc, "telesurgery_low_latency_patch")
    with pytest.raises(RuntimeError, match="build_pynvvideocodec.py"):
        GpuCodec(Config(codec="h264"), encode=True)


def test_native_decode_keeps_owned_rgb_pixels_on_gpu(monkeypatch):
    import cupy as cp
    import cupyx

    def forbidden(*args, **kwargs):
        pytest.fail("Native display downloaded decoded pixels to host memory")

    monkeypatch.setattr(cupyx, "empty_pinned", forbidden)
    with contextlib.ExitStack() as stack:
        encoder = GpuCodec(Config(codec="h264", qp=18), encode=True)
        decoder = GpuCodec(Config(codec="h264"), encode=False)
        stack.callback(encoder.close)
        stack.callback(decoder.close)
        images = []
        for sequence, bgr in enumerate(([30, 90, 170], [180, 70, 20])):
            pixels = np.full((240, 320, 3), bgr, dtype=np.uint8)
            packet = encoder.encode(Frame(VideoHeader(sequence, 1, 320, 240), pixels))
            image = decoder.decode(*packet, on_device=True).image
            assert isinstance(image, cp.ndarray)
            images.append(image)
        # A later decode must not overwrite a tensor still being displayed.
        np.testing.assert_allclose(cp.asnumpy(images[0][120, 160]), [170, 90, 30], atol=4)
        np.testing.assert_allclose(cp.asnumpy(images[1][120, 160]), [20, 70, 180], atol=4)
