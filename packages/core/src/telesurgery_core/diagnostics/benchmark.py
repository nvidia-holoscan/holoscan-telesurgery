# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded software timing statistics; these are not photon-to-glass measurements."""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from copy import copy
from pathlib import Path

import numpy as np
from telesurgery_core.diagnostics.trace import Paths


class Samples:
    """Exact lifetime aggregates and percentiles over the latest bounded window."""

    def __init__(self, capacity=10_000, *, budget=None):
        self.values = deque(maxlen=capacity)
        self.budget, self.budget_misses = budget, 0
        self.count = self.invalid = 0
        self.total = 0.0
        self.minimum = math.inf
        self.maximum = -math.inf

    def add(self, value):
        if not math.isfinite(value) or value < 0:
            self.invalid += 1
            return
        self.values.append(value)
        self.count += 1
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        if self.budget is not None and value > self.budget:
            self.budget_misses += 1

    def report(self):
        result = {"count": self.count, "invalid": self.invalid, "window_count": len(self.values)}
        if self.budget is not None:
            result.update(budget=self.budget, budget_misses=self.budget_misses)
        if self.count:
            p50, p95, p99, p99_9 = np.percentile(self.values, [50, 95, 99, 99.9], method="linear")
            result.update(
                min=self.minimum,
                mean=self.total / self.count,
                p50=float(p50),
                p95=float(p95),
                p99=float(p99),
                p99_9=float(p99_9),
                window_stddev=float(np.std(self.values)),
                max=self.maximum,
            )
        return result

    def snapshot(self):
        result = copy(self)
        result.values = self.values.copy()
        return result


class Benchmark:
    def __init__(self):
        self.warmup_seconds = 2.0
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.steady_samples = {}
            self.samples = {}
            self.frames = self.sequence_gaps = self.sequence_resets = 0
            self.first_at = self.last_at = None
            self.last_sequence = None
            self.max_sim_command_sequence = -1
            self.first_sim_command_sequence = None
            self.delivery_status = "Clock synchronization required"
            self.delivery_clock_error_ms = None
            self.paths = Paths()

    def finish(self, trace, boundary):
        if trace is not None:
            with self._lock:
                if self.frames > 1 and self.last_at - self.first_at >= self.warmup_seconds:
                    self.paths.add(trace, boundary)

    def add(self, name, value):
        with self._lock:
            self._add(name, value)

    def _add(self, name, value):
        # A diagnostic delivery stall threshold, not a capture-to-display deadline.
        budget = 100 if name == "receive_interval_ms" else None
        self.samples.setdefault(name, Samples(budget=budget)).add(value)
        if self.frames > 1 and self.last_at - self.first_at >= self.warmup_seconds:
            self.steady_samples.setdefault(name, Samples(budget=budget)).add(value)

    def observe(self, header):
        with self._lock:
            now = time.monotonic()
            if self.first_at is None:
                self.first_at = now
                self.first_sim_command_sequence = header.sim_command_sequence
            previous, self.last_at = self.last_at, now
            self.frames += 1
            if self.last_sequence is not None:
                gap = header.sequence - self.last_sequence - 1
                self.sequence_gaps += max(0, gap)
                self.sequence_resets += int(gap < 0)
                if gap < 0:
                    previous = None  # A restarted producer begins a new delivery cadence.
            if previous is not None:
                self._add("receive_interval_ms", (now - previous) * 1000)
            self.last_sequence = header.sequence
            self.max_sim_command_sequence = max(
                self.max_sim_command_sequence, header.sim_command_sequence
            )

    def encoded(self, header, data):
        self.add("payload_bytes", len(data))
        for name in ("acquisition", "encoder_queue", "encode", "pack"):
            duration = getattr(header, name + "_ns")
            if duration:
                self.add(name + "_ms", duration / 1e6)
        self.add(
            "compression_ratio",
            header.width * header.height * (7 if header.depth_bytes else 3) / len(data),
        )

    def delivery(self, timing):
        with self._lock:
            if timing.get("frame_bytes") is not None:
                self._add("transport_frame_bytes", timing["frame_bytes"])
            self.delivery_status = timing["status"]
            self.delivery_clock_error_ms = timing.get("error_ms")
            if timing.get("delivery_ms") is not None:
                self._add("delivery_ms", timing["delivery_ms"])
                self._add("clock_error_ms", timing["error_ms"])

    def report(self):
        with self._lock:
            elapsed = (self.last_at - self.first_at) if self.frames > 1 else 0
            steady = {name: values.snapshot() for name, values in self.steady_samples.items()}
            samples = {name: values.snapshot() for name, values in self.samples.items()}
            paths = self.paths.snapshot()
            result = {
                "schema_version": 1,
                "steady_warmup_seconds": self.warmup_seconds,
                "percentiles": "P50/P95/P99/P99.9, linear interpolation over the latest "
                "10000 valid samples per metric; "
                "min/mean/max and budget misses are lifetime; stddev uses the percentile window",
                "frames": self.frames,
                "last_frame_age_ms": max(0, time.monotonic() - self.last_at) * 1000
                if self.last_at is not None
                else None,
                "observation_seconds": elapsed,
                "fps": (self.frames - 1) / elapsed if elapsed else 0,
                "sequence_gaps": self.sequence_gaps,
                "sequence_resets": self.sequence_resets,
                "delivery_status": self.delivery_status,
                "delivery_clock_error_ms": self.delivery_clock_error_ms,
                "first_sim_command_sequence": self.first_sim_command_sequence,
                "max_sim_command_sequence": self.max_sim_command_sequence,
            }
        # Sorting the bounded copies must not hold up frame acquisition.
        result["steady_metrics"] = {
            name: values.report() for name, values in sorted(steady.items())
        }
        result["metrics"] = {name: values.report() for name, values in sorted(samples.items())}
        result["path"] = Paths.report(*paths)
        return result


def write_report(path, report):
    if path is not None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
