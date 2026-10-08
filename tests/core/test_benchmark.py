# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
from dataclasses import replace

import pytest
from telesurgery_core.diagnostics.benchmark import Benchmark, Samples
from telesurgery_core.transport.protocol import VideoHeader


def test_bounded_percentiles_and_lifetime_aggregates():
    samples = Samples(capacity=3)
    for value in [1, 2, 3, 4, 5, -1, float("nan"), float("inf")]:
        samples.add(value)
    report = samples.report()
    assert report["count"] == 5
    assert report["invalid"] == 3
    assert report["window_count"] == 3
    assert (report["min"], report["mean"], report["max"]) == (1, 3, 5)
    assert report["p50"] == 4
    assert report["p95"] == pytest.approx(4.9)
    assert report["p99"] == pytest.approx(4.98)
    assert report["p99_9"] == pytest.approx(4.998)
    assert report["window_stddev"] == pytest.approx((2 / 3) ** 0.5)
    json.dumps(report, allow_nan=False)


def test_tail_percentiles_include_rare_stalls():
    samples = Samples()
    for value in [1] * 9980 + [100] * 20:
        samples.add(value)
    report = samples.report()
    assert report["window_count"] == 10_000
    assert report["p50"] == report["p95"] == report["p99"] == 1
    assert report["p99_9"] == 100


def test_empty_and_single_sample_percentiles():
    samples = Samples()
    assert samples.report() == {"count": 0, "invalid": 0, "window_count": 0}
    samples.add(7)
    report = samples.report()
    assert all(report[key] == 7 for key in ("p50", "p95", "p99", "p99_9"))


def test_budget_misses_include_samples_outside_the_percentile_window():
    samples = Samples(capacity=2, budget=100)
    for value in (101, 100, 1, float("nan")):
        samples.add(value)
    report = samples.report()
    assert report["count"] == 3 and report["window_count"] == 2
    assert report["budget"] == 100 and report["budget_misses"] == 1
    assert report["invalid"] == 1


def test_delivery_interval_jitter_and_stalls_use_local_clock(monkeypatch):
    clock = iter([0.0, 0.05, 0.1, 0.3])
    monkeypatch.setattr(
        "telesurgery_core.diagnostics.benchmark.time.monotonic", lambda: next(clock, 0.3)
    )
    benchmark = Benchmark()
    for sequence in range(4):
        benchmark.observe(VideoHeader(sequence, 1, 100, 100))
    intervals = benchmark.report()["metrics"]["receive_interval_ms"]
    assert intervals["count"] == 3
    assert intervals["p50"] == 50 and intervals["budget_misses"] == 1
    assert intervals["window_stddev"] == pytest.approx(50 * 2**0.5)


def test_stage_boundaries_clocks_gaps_and_resets(monkeypatch):
    clock = iter([0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(
        "telesurgery_core.diagnostics.benchmark.time.monotonic", lambda: next(clock, 0.3)
    )
    benchmark = Benchmark()
    header = VideoHeader(10, 1000000000, 100, 100, encode_ns=2000000, sim_command_sequence=0)
    for sequence, command in [(10, 0), (12, 2), (0, 0), (1, 0)]:
        current = replace(header, sequence=sequence, sim_command_sequence=command)
        benchmark.observe(current)
        benchmark.encoded(current, bytes(1000))
    report = benchmark.report()
    assert report["sequence_gaps"] == report["sequence_resets"] == 1
    assert report["fps"] == pytest.approx(10)
    assert report["first_sim_command_sequence"] == 0
    assert report["max_sim_command_sequence"] == 2
    metrics = report["metrics"]
    assert metrics["encode_ms"]["mean"] == 2
    assert metrics["compression_ratio"]["mean"] == 30
    assert metrics["payload_bytes"]["p99"] == 1000
    assert report["last_frame_age_ms"] == 0


def test_stream_restart_does_not_count_stopped_time_as_frame_spacing(monkeypatch):
    clock = iter([0.0, 0.02, 120.0, 120.02, 120.22])
    monkeypatch.setattr(
        "telesurgery_core.diagnostics.benchmark.time.monotonic", lambda: next(clock, 120.22)
    )
    benchmark = Benchmark()
    for sequence in [0, 1, 0, 1, 2]:
        benchmark.observe(VideoHeader(sequence, 1, 100, 100))
    report = benchmark.report()
    intervals = report["metrics"]["receive_interval_ms"]
    assert report["sequence_resets"] == 1
    assert intervals["count"] == 3
    assert intervals["p50"] == pytest.approx(20)
    assert intervals["max"] == pytest.approx(200)
    assert intervals["budget_misses"] == 1  # A stall within the new stream is still measured.


def test_optional_video_timings_are_validated():
    doc = {
        "version": 1,
        "sequence": 0,
        "captured_ns": 10,
        "width": 1,
        "height": 1,
    }
    header = VideoHeader.decode(json.dumps(doc).encode())
    assert header.encode_ns == 0 and header.sim_command_sequence == -1
    for value in [True, -1, "100", 1.5]:
        with pytest.raises(ValueError):
            VideoHeader.decode(json.dumps({**doc, "encode_ns": value}).encode())


def test_percentile_work_does_not_hold_frame_lock(monkeypatch):
    import telesurgery_core.diagnostics.benchmark as module

    benchmark = Benchmark()
    benchmark.add("encode_ms", 2)
    percentile = module.np.percentile

    def inspect_snapshot(values, *args, **kwargs):
        assert benchmark._lock.acquire(blocking=False)
        benchmark._lock.release()
        benchmark.add("encode_ms", 100)
        return percentile(values, *args, **kwargs)

    monkeypatch.setattr(module.np, "percentile", inspect_snapshot)
    report = benchmark.report()["metrics"]["encode_ms"]
    assert report["count"] == 1 and report["p99_9"] == 2
