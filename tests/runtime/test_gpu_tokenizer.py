# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Real public models, device decoding, preview conversion and live encoding changes."""

import asyncio
import importlib.util
import json
import time
from dataclasses import asdict, replace

import numpy as np
import pytest
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.codecs import CodecWorker
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame
from telesurgery_core.video.tokenizer_model import CODEC, PROFILE, payload_size

pytest.importorskip("tensorrt" if importlib.util.find_spec("tensorrt") else "tensorrt_bindings")
pytest.importorskip("cupy")
pytestmark = pytest.mark.gpu


@pytest.mark.parametrize("width,height", [(1280, 720), (1920, 1080)])
def test_gpu_round_trip_depth_and_owned_native_output(width, height):
    config = Config(codec=CODEC, width=width, height=height)
    encoder, decoder = CodecWorker(config, encode=True), CodecWorker(config, encode=False)
    pixels = np.full((height, width, 3), [40, 90, 180], np.uint8)
    depth = np.full((height, width), 0.5, np.float32)
    original = VideoHeader(9, time.time_ns(), width, height, sim_command_sequence=21)
    try:
        header, data = encoder.encode(Frame(original, pixels, depth=depth))
        assert header.codec_profile == PROFILE
        assert len(data) - header.depth_bytes == payload_size(width, height)
        assert (header.sequence, header.captured_ns, header.sim_command_sequence) == (
            original.sequence,
            original.captured_ns,
            21,
        )
        first = decoder.decode_device(header, data)
        saved = first.image.get()
        np.testing.assert_allclose(saved[height // 2, width // 2], [180, 90, 40], atol=10)
        np.testing.assert_array_equal(first.depth, depth)
        # Decoding another frame must not overwrite an image retained by Holoviz.
        second_header, second_data = encoder.encode(
            Frame(replace(original, sequence=12), 255 - pixels)
        )
        decoder.decode_device(second_header, second_data)
        np.testing.assert_array_equal(first.image.get(), saved)
        host = decoder.decode(header, data)
        assert np.abs(host.image.astype(float) - pixels).mean() < 10
    finally:
        decoder.close()
        encoder.close()


def test_encoding_change_keeps_capture_and_frame_sequence(tmp_path):
    from telesurgery_runtime.application.video import Encode
    from telesurgery_runtime.application.viewer import ReceiveDecode

    config = Config(width=1280, height=720)
    path = tmp_path / "camera.json"
    path.write_text(json.dumps({"camera": asdict(config)}))
    stage = Encode(config, path)
    viewer = ReceiveDecode()
    stage.start()
    viewer.start()
    pixels = np.full((720, 1280, 3), [40, 90, 180], np.uint8)
    sequence = 0
    try:
        for codec in ("h264", CODEC, "h264", CODEC):
            path.write_text(json.dumps({"camera": asdict(replace(config, codec=codec))}))
            deadline = time.monotonic() + 120
            while True:
                original = VideoHeader(sequence, time.time_ns(), 1280, 720)
                header, data = stage.compute(Frame(original, pixels))
                assert header.sequence == sequence
                sequence += 1
                if header.codec == codec:
                    break
                assert time.monotonic() < deadline
                time.sleep(0.02)
            viewer.put(asdict(header), data)
            rgb = viewer.compute()
            np.testing.assert_allclose(rgb[360, 640].get(), [180, 90, 40], atol=10)
    finally:
        viewer.stop()
        stage.stop()


@pytest.mark.asyncio
async def test_two_preview_feeds_preserve_depth_and_switch_back():
    from telesurgery.server.media import EncodedTrack, Media
    from telesurgery_core.video.depth import unpack

    config = Config(codec=CODEC, width=1280, height=720)
    encoder = CodecWorker(config, encode=True)
    h264 = CodecWorker(replace(config, codec="h264"), encode=True)
    decoder = CodecWorker(replace(config, codec="h264"), encode=False)
    media = Media()
    try:
        original = VideoHeader(5, time.time_ns(), 1280, 720)
        pixels = np.full((720, 1280, 3), [40, 90, 180], np.uint8)
        depth = np.full((720, 1280), 0.7, np.float32)
        header, data = encoder.encode(Frame(original, pixels, depth=depth))
        await asyncio.gather(*(media.put(camera, asdict(header), data) for camera in ("a", "b")))
        tracks = [EncodedTrack(media.feeds[c]) for c in ("a", "b")]
        packets = await asyncio.wait_for(asyncio.gather(*(t.recv() for t in tracks)), 120)
        for track, packet in zip(tracks, packets, strict=True):
            preview_header = VideoHeader(**track.feed.packet[0])
            assert preview_header.captured_ns == original.captured_ns
            assert preview_header.sequence == original.sequence
            assert track.depth_size == (1280, 720)
            np.testing.assert_array_equal(unpack(preview_header, track.depth), depth)
            frame = decoder.decode(replace(preview_header, depth_bytes=0), bytes(packet))
            assert np.abs(frame.image.astype(float) - pixels).mean() < 12
        back_header, back_data = h264.encode(Frame(replace(original, sequence=6), pixels))
        await media.put("a", asdict(back_header), back_data)
        packet = await tracks[0].recv()
        assert bytes(packet) == back_data
        assert not tracks[0].depth
    finally:
        await media.clear()
        encoder.close()
        h264.close()
        decoder.close()


def test_failed_encoder_change_keeps_stream_and_allows_recovery(tmp_path, monkeypatch):
    from telesurgery_runtime.application import video

    config = Config(width=1280, height=720)
    path = tmp_path / "camera.json"
    path.write_text(json.dumps({"camera": asdict(config)}))
    stage = video.Encode(config, path)
    stage.start()
    original = stage.codec
    builds = []

    def build(requested, **kwargs):
        builds.append(requested.codec)
        if requested.codec == CODEC:
            raise RuntimeError("Model download unavailable")
        return CodecWorker(requested, **kwargs)

    monkeypatch.setattr(video, "CodecWorker", build)
    pixels = np.full((720, 1280, 3), 80, np.uint8)
    frame = Frame(VideoHeader(1, time.time_ns(), 1280, 720), pixels)
    try:
        path.write_text(json.dumps({"camera": asdict(replace(config, codec=CODEC))}))
        deadline = time.monotonic() + 10
        while not path.with_suffix(".error").exists():
            assert stage.compute(frame)[0].codec == "h264"
            assert time.monotonic() < deadline
            time.sleep(0.02)
        for _ in range(5):
            assert stage.compute(frame)[0].codec == "h264"
        assert stage.codec is original
        assert builds == [CODEC]
        assert "Model download unavailable" in path.with_suffix(".error").read_text()
        path.write_text(json.dumps({"camera": asdict(config)}))
        stage.check_at = 0
        assert stage.compute(frame)[0].codec == "h264"
        assert not path.with_suffix(".error").exists()
    finally:
        stage.stop()
