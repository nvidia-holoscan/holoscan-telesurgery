# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A latency breakdown must describe matched frames and account for the entire measured path."""

import numpy as np
import pytest
from telesurgery_core.diagnostics.trace import Paths, arrive, mark, source, wire
from telesurgery_core.transport.protocol import VideoHeader


@pytest.mark.parametrize("started, expected", [(5_000_000, 15_000_000), (-1, 0), (0, 0)])
def test_capture_starts_at_buffer_handoff_and_excludes_read_wait(monkeypatch, started, expected):
    from types import SimpleNamespace

    from telesurgery_core.adapters.base import CameraSample
    from telesurgery_core.video.config import Config
    from telesurgery_runtime.video import Capture

    monkeypatch.setattr("telesurgery_runtime.video.time.perf_counter_ns", lambda: 20_000_000)
    camera = SimpleNamespace(
        read=lambda: CameraSample(np.zeros((32, 32, 3)), 1, started_ns=started)
    )
    header = Capture(Config(), camera).compute().header
    assert header.acquisition_ns == expected
    assert header.source_started_ns == (20_000_000 if started == 0 else max(0, started))


def test_adjacent_boundaries_sum_from_capture_to_display_handoff():
    start = 1_000_000_000
    header = VideoHeader(
        3,
        1,
        32,
        32,
        acquisition_ns=2_000_000,
        encoder_queue_ns=3_000_000,
        encode_ns=5_000_000,
        source_started_ns=start,
        encoded_ns=start + 10_000_000,
    )
    trace = source(header)
    trace = mark(trace, "source_relay_ms", start + 12_000_000)
    trace = mark(trace, "source_queue_ms", start + 15_000_000)
    trace = mark(trace, "send_queue_ms", start + 18_000_000)
    assert sum(trace["stages"].values()) == 18
    # The source node's monotonic epoch need not match the surgeon's epoch.
    trace = arrive(wire(trace), {"received_ns": 10_000_000, "delivery_ms": 20, "error_ms": 0.1})
    trace = mark(trace, "receiver_queue_ms", 11_000_000)
    trace = mark(trace, "decode_ms", 15_000_000)
    trace = mark(trace, "render_submit_ms", 17_000_000)
    assert sum(trace["stages"].values()) == 45
    assert trace["error_ms"] == pytest.approx(0.1)
    assert "at_ns" not in wire(trace)


def test_total_percentiles_use_matching_frames_not_independent_stage_percentiles():
    paths = Paths()
    for encode, transport in [(0, 100), (0, 0), (100, 0), (2, 4), (0, 150)]:
        paths.add(
            {"stages": {"encode_ms": encode, "transport_ms": transport}, "error_ms": 0}, "send"
        )
    report = Paths.report(*paths.snapshot())
    assert np.median([0, 0, 100, 2, 0]) + np.median([100, 0, 0, 4, 150]) != report["total"]["p50"]
    for key, expected in zip(
        ("p50", "p95", "p99", "p99_9"),
        np.percentile([100, 0, 100, 6, 150], [50, 95, 99, 99.9]),
        strict=True,
    ):
        assert report["total"][key] == pytest.approx(expected)
        assert sum(s[key] for s in report["stages"].values()) == pytest.approx(expected)


def test_unresolved_hop_remains_unknown_and_cannot_leave_a_stale_total():
    trace = arrive(
        {"stages": {"encode_ms": 2}, "error_ms": 0},
        {"received_ns": 100, "status": "Clock synchronization required"},
    )
    assert trace["stages"]["transport_ms"] is None
    paths = Paths()
    paths.add({"stages": {"encode_ms": 2, "transport_ms": 4}, "error_ms": 0}, "send")
    paths.add(trace, "send")
    report = Paths.report(*paths.snapshot())
    assert report["missing"] == ["transport_ms"]
    assert not report["total"]
    assert report["partial"]["encode_ms"]["p50"] == 2
    assert arrive({"stages": {"encode_ms": -1}}, {"received_ns": 100}) is None
    assert source(VideoHeader(0, 1, 32, 32, encoded_ns=10)) is None


def test_hour_history_is_bounded_and_survives_raw_window_eviction(monkeypatch):
    import telesurgery_core.diagnostics.trace as module

    now = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    paths = Paths()
    for second in range(3800):
        now[0] = second
        for _ in range(3):
            paths.add({"stages": {"encode_ms": 1, "transport_ms": 2}, "error_ms": 0}, "send")
    report = Paths.report(*paths.snapshot())
    assert len(paths.values) == 10000
    assert len(report["history"]) == 721
    assert report["history"][-1]["at"] - report["history"][0]["at"] == 3600
    assert all(s["p99_9"] == 3 for s in report["history"])
    assert report["history_end"] == 3799


@pytest.mark.asyncio
async def test_only_sent_frames_are_timed_and_fanout_does_not_mutate_trace():
    import asyncio
    import json
    import time

    from telesurgery_core.transport.peer import Peer

    class Writer:
        def __init__(self):
            self.parts = []

        def write(self, data):
            self.parts.append(data)

        async def drain(self):
            await asyncio.sleep(0)

        def close(self):
            pass

        async def wait_closed(self):
            pass

    sent = []
    writer = Writer()
    peer = Peer(
        None,
        writer,
        None,
        video_sent=lambda camera, trace, size: sent.append({**trace, "frame_bytes": size}),
    )
    trace = {"at_ns": time.monotonic_ns() - 2_000_000, "stages": {"encode_ms": 2}, "error_ms": 0}
    peer.event("video", {"camera": "camera", "trace": trace}, b"old", stream="camera")
    peer.event("video", {"camera": "camera", "trace": trace}, b"latest", stream="camera")
    peer.sender = asyncio.create_task(peer._send())
    try:
        async with asyncio.timeout(1):
            while not sent:
                await asyncio.sleep(0.001)
        assert len(sent) == 1
        assert writer.parts[-1] == b"latest"
        assert sent[0]["frame_bytes"] == sum(len(part) for part in writer.parts)
        assert sent[0]["stages"]["send_queue_ms"] >= 2
        assert list(trace["stages"]) == ["encode_ms"]
        message = json.loads(writer.parts[1])
        assert "at_ns" not in message["params"]["trace"]
        assert message["params"]["timing"]["mono_ns"] == sent[0]["at_ns"]
    finally:
        await peer.close()
