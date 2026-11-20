# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Real NVIDIA codec tests; these never substitute a software encoder/decoder."""

import contextlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import replace

import numpy as np
import pytest
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.codecs import GpuCodec, create_codec
from telesurgery_core.video.config import Config
from telesurgery_core.video.formats import (
    h264_dimensions,
    h265_dimensions,
    video_frame,
)
from telesurgery_core.video.model import Frame
from telesurgery_core.video.reference import MissingReference

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
    config = Config(codec=codec)
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
            assert video_frame(codec, data) == (
                (320, 240) if header.keyframe else None,
                header.keyframe,
            )
            assert header.captured_ns == originals[header.sequence][0].captured_ns
            assert header.encode_ns > 0
            assert header.encoder_queue_ns >= 1_000_000
        predicted = codec != "nvjpeg"
        assert [h.keyframe for h, _ in packets] == [True] + [not predicted] * 11
        decoder = GpuCodec(config, encode=False)
        stack.callback(decoder.close)
        held_frames = []
        if predicted:
            # A decoder joining mid-GOP, or after a dropped frame, must wait for an IDR.
            for header, data in (packets[3], packets[4]):
                with pytest.raises(MissingReference):
                    decoder.decode(header, data)
            encoder.request_keyframe()
            sequence = 12
            pixels = originals[11][1]
            header = VideoHeader(sequence, time.time_ns(), 320, 240, sim_command_sequence=sequence)
            originals[sequence] = (header, pixels)
            packets.append(encoder.encode(Frame(header, pixels)))
            assert packets[-1][0].keyframe and packets[-1][0].gop != packets[0][0].gop
            order = (packets[-1], packets[0], packets[1], packets[2])
        else:
            # Independent frames: join halfway, skip, and replay an earlier frame.
            order = (packets[3], packets[7], packets[0])
        for header, data in order:
            frame = decoder.decode(header, data)
            expected = originals[header.sequence][1]
            assert np.abs(frame.image.astype(float) - expected).mean() < 4
            assert frame.header.sim_command_sequence == header.sequence
            held_frames.append((frame, frame.image.copy()))
        # The pinned pool must not overwrite frames still owned by the viewer.
        for held, saved in held_frames:
            np.testing.assert_array_equal(held.image, saved)
        if predicted:
            # Loss during playback: packets[3] never arrives, so the frames after it
            # are refused until a fresh IDR, and the same decoder then continues.
            for header, data in (packets[4], packets[5]):
                with pytest.raises(MissingReference):
                    decoder.decode(header, data)
            encoder.request_keyframe()
            for sequence in (13, 14):
                header = VideoHeader(sequence, time.time_ns(), 320, 240)
                recovered = encoder.encode(Frame(header, originals[11][1]))
                assert recovered[0].keyframe == (sequence == 13)
                frame = decoder.decode(*recovered)
                assert np.abs(frame.image.astype(float) - originals[11][1]).mean() < 4
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

    config = Config(codec=codec)
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

    from telesurgery_runtime.application.viewer import ReceiveDecode

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


def test_native_viewer_waits_for_keyframe_and_requests_one():
    from dataclasses import asdict

    from telesurgery_runtime.application.viewer import ReceiveDecode

    config = Config(codec="h264")
    encoder = GpuCodec(config, encode=True)
    viewer = ReceiveDecode()
    viewer.start()
    try:
        pixels = np.full((240, 320, 3), [20, 90, 170], dtype=np.uint8)
        packets = [
            encoder.encode(Frame(VideoHeader(i, time.time_ns(), 320, 240), pixels))
            for i in range(3)
        ]
        # Joining mid-GOP: no picture, and one request for an IDR per interval.
        viewer.put(asdict(packets[1][0]), packets[1][1])
        assert viewer.compute() is None
        assert viewer.keyframe_due()
        assert not viewer.keyframe_due()
        viewer.put(asdict(packets[2][0]), packets[2][1])
        assert viewer.compute() is None
        encoder.request_keyframe()
        header, data = encoder.encode(Frame(VideoHeader(3, time.time_ns(), 320, 240), pixels))
        viewer.put(asdict(header), data)
        np.testing.assert_allclose(viewer.compute()[120, 160].get(), [170, 90, 20], atol=4)
        assert not viewer.keyframe_due()
    finally:
        viewer.stop()
        encoder.close()


def test_native_viewer_decodes_a_short_backlog_in_order_without_a_keyframe():
    from dataclasses import asdict

    from telesurgery_runtime.application.viewer import BACKLOG, ReceiveDecode

    encoder = GpuCodec(Config(codec="h264"), encode=True)
    viewer = ReceiveDecode()
    viewer.start()
    try:

        def send(index):
            pixels = np.full((240, 320, 3), [20 + index * 10, 90, 170], dtype=np.uint8)
            header, data = encoder.encode(
                Frame(VideoHeader(index, time.time_ns(), 320, 240), pixels)
            )
            viewer.put(asdict(header), data)

        send(0)
        assert viewer.compute() is not None
        # The viewer was busy while three predicted frames arrived: all are decoded,
        # the newest is shown, and no keyframe is needed.
        for index in (1, 2, 3):
            send(index)
        np.testing.assert_allclose(viewer.compute()[120, 160].get(), [170, 90, 50], atol=4)
        assert not viewer.keyframe_due()
        report = viewer.benchmark.report()["metrics"]
        assert report["caught_up_frames"]["count"] == 2 and "undecodable_frames" not in report
        # A backlog too long to be worth decoding is dropped and repaired by an IDR.
        for index in range(4, 4 + BACKLOG + 1):
            send(index)
        assert viewer.compute() is None
        assert viewer.keyframe_due()
        encoder.request_keyframe()
        send(40)
        send(41)
        np.testing.assert_allclose(viewer.compute()[120, 160].get(), [170, 90, 174], atol=4)
        assert viewer.benchmark.report()["metrics"]["keyframe_wait_ms"]["count"] == 1
    finally:
        viewer.stop()
        encoder.close()


def test_camera_worker_encodes_an_idr_when_the_node_asks(tmp_path):
    from dataclasses import asdict

    from telesurgery_core.video.reference import KEYFRAME_SUFFIX
    from telesurgery_runtime.application.video import Encode

    config = Config(codec="h264", width=320, height=240)
    settings = tmp_path / "camera.json"
    settings.write_text(json.dumps({"camera": asdict(config)}))
    stage = Encode(config, settings)
    stage.start()
    try:
        pixels = np.full((240, 320, 3), [20, 90, 170], dtype=np.uint8)
        kinds = []
        for sequence in range(6):
            if sequence == 4:
                settings.with_suffix(KEYFRAME_SUFFIX).touch()
            header = VideoHeader(sequence, time.time_ns(), 320, 240)
            kinds.append(stage.compute(Frame(header, pixels))[0].keyframe)
        assert kinds == [True, False, False, False, True, False]
        assert not settings.with_suffix(KEYFRAME_SUFFIX).exists()
    finally:
        stage.stop()


def _encode_moving_noise(config, frames=45):
    """Sizes, keyframe flags and bytes for textured content that moves every frame."""
    rng = np.random.default_rng(7)
    # Coarse blocks with fine grain: detailed, but not incompressible like white noise.
    blocks = np.kron(rng.integers(0, 256, (68, 88, 3), dtype=np.uint8), np.ones((8, 8, 1)))
    texture = (blocks + rng.integers(-12, 13, blocks.shape)).clip(0, 255).astype(np.uint8)
    encoder = GpuCodec(config, encode=True)
    decoder = GpuCodec(config, encode=False)
    try:
        packets = []
        for index in range(frames):
            shift = index % 64
            pixels = np.ascontiguousarray(texture[shift : shift + 480, shift : shift + 640])
            header, data = encoder.encode(Frame(VideoHeader(index, index + 1, 640, 480), pixels))
            assert decoder.decode(header, data).image.shape == (480, 640, 3)
            packets.append((len(data), header.keyframe, data))
        return packets
    finally:
        encoder.close()
        decoder.close()


@pytest.mark.parametrize("codec", ["h264", "h265"])
def test_rate_control_modes_and_advanced_settings_change_real_nvenc_output(codec):
    def run(**settings):
        return _encode_moving_noise(Config(codec=codec, width=640, height=480, fps=30, **settings))

    budget = 2_000_000 / 30 / 8
    cbr = run(rate_control="cbr", bitrate_mbps=2)
    assert [keyframe for _, keyframe, _ in cbr] == [True] + [False] * 44

    # Check the per-frame budget with VBR when the max equals the average.
    equal_rates = run(rate_control="vbr", bitrate_mbps=2, max_bitrate_mbps=2)
    sizes = [size for size, _, _ in equal_rates]
    assert max(sizes[1:]) <= budget * 1.25
    assert sizes[0] <= budget * 3
    assert budget * 0.4 <= np.mean(sizes[5:]) <= budget * 1.1

    vbr = run(rate_control="vbr", bitrate_mbps=2)
    assert np.mean([size for size, _, _ in vbr][5:]) <= budget * 1.5

    # Constant QP has no budget: a lower QP spends several times the bits.
    sharp = run(rate_control="cqp", qp=20)
    soft = run(rate_control="cqp", qp=40)
    assert np.mean([size for size, _, _ in sharp]) > 3 * np.mean([size for size, _, _ in soft])
    assert [keyframe for _, keyframe, _ in sharp] == [True] + [False] * 44

    # A QP ceiling overrides a budget that is too small for this content.
    starved = run(bitrate_mbps=0.5)
    capped = run(bitrate_mbps=0.5, encoder_extra="qmax=30")
    assert np.mean([size for size, _, _ in capped]) > 1.5 * np.mean(
        [size for size, _, _ in starved]
    )

    # gop_seconds moves the periodic IDR; the other keys change the bitstream.
    tuned = run(bitrate_mbps=2, encoder_extra="gop_seconds=1\naq=8\ntemporalaq=on\nvbv_frames=2")
    assert [index for index, (_, keyframe, _) in enumerate(tuned) if keyframe] == [0, 30]
    assert [data for _, _, data in tuned[:30]] != [data for _, _, data in cbr[:30]]
    assert run(bitrate_mbps=2, encoder_extra="multipass=qres")[5][2] != cbr[5][2]


@pytest.mark.parametrize("codec", ["h264", "h265"])
def test_vbr_easy_scenes_use_less_than_the_max_bitrate_and_carry_no_filler(codec):
    config = Config(
        codec=codec,
        width=640,
        height=480,
        fps=30,
        rate_control="vbr",
        bitrate_mbps=4,
        max_bitrate_mbps=4,
    )
    encoder = GpuCodec(config, encode=True)
    try:
        pixels = np.full((480, 640, 3), [20, 90, 170], dtype=np.uint8)
        sizes = []
        for index in range(30):
            _, data = encoder.encode(Frame(VideoHeader(index, index + 1, 640, 480), pixels))
            units = [unit for unit in re.split(b"\x00\x00\x00?\x01", data) if unit]
            kinds = [u[0] & 31 if codec == "h264" else u[0] >> 1 & 63 for u in units]
            assert (12 if codec == "h264" else 38) not in kinds  # Filler data.
            sizes.append(len(data))
        assert max(sizes[1:]) < 4_000_000 / 30 / 8 / 10
    finally:
        encoder.close()


def test_h264_rejects_stock_binding(monkeypatch):
    import PyNvVideoCodec as nvc

    monkeypatch.delattr(nvc, "telesurgery_low_latency_patch")
    with pytest.raises(RuntimeError, match="scripts/builders/codecs.py"):
        GpuCodec(Config(codec="h264"), encode=True)


def test_native_decode_keeps_owned_rgb_pixels_on_gpu(monkeypatch):
    import cupy as cp
    import cupyx

    def forbidden(*args, **kwargs):
        pytest.fail("Native display downloaded decoded pixels to host memory")

    monkeypatch.setattr(cupyx, "empty_pinned", forbidden)
    with contextlib.ExitStack() as stack:
        encoder = GpuCodec(Config(codec="h264"), encode=True)
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
