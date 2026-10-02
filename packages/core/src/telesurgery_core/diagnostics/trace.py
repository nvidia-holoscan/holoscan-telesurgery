# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Per-frame software timing. Adjacent boundaries cover the path without overlap."""

import math
import time
from array import array
from collections import deque

import numpy as np

STAGES = (
    "acquisition_ms",
    "encoder_queue_ms",
    "encode_ms",
    "pack_ms",
    "source_relay_ms",
    "source_queue_ms",
    "send_queue_ms",
    "transport_ms",
    "receiver_queue_ms",
    "decode_ms",
    "unpack_ms",
    "render_submit_ms",
    "browser_queue_ms",
    "browser_decode_ms",
    "browser_playout_ms",
)


def source(header):
    duration = header.acquisition_ns + header.encoder_queue_ns + header.encode_ns + header.pack_ns
    if not header.source_started_ns or header.encoded_ns - header.source_started_ns != duration:
        return None
    return {
        "at_ns": header.encoded_ns,
        "stages": {
            "acquisition_ms": header.acquisition_ns / 1e6,
            "encoder_queue_ms": header.encoder_queue_ns / 1e6,
            **(
                {"pack_ms": header.pack_ns / 1e6}
                if header.codec == "raw-bgr8"
                else {"encode_ms": header.encode_ns / 1e6}
            ),
        },
        "error_ms": 0,
    }


def mark(trace, stage, now=None):
    if trace is None:
        return None
    now = time.monotonic_ns() if now is None else now
    duration = (now - trace["at_ns"]) / 1e6
    return {
        **trace,
        "at_ns": now,
        "stages": {**trace["stages"], stage: duration if duration >= 0 else None},
    }


def wire(trace):
    return {k: trace[k] for k in ("stages", "error_ms")} if trace else None


def arrive(trace, timing, stage="transport_ms"):
    if not isinstance(trace, dict) or not isinstance(trace.get("stages"), dict):
        return None
    stages = trace["stages"]
    if not stages or any(
        k not in STAGES
        or (v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v < 0))
        for k, v in stages.items()
    ):
        return None
    error = trace.get("error_ms")
    error = error if type(error) in (int, float) and math.isfinite(error) and error >= 0 else None
    local_error = timing.get("error_ms")
    return {
        "at_ns": timing["received_ns"],
        "stages": {**stages, stage: timing.get("delivery_ms")},
        "error_ms": error + local_error if error is not None and local_error is not None else None,
    }


class Paths:
    """Bounded matched-frame samples; interpolation uses the total's rank for every stage."""

    def __init__(self):
        self.values = deque(maxlen=10_000)
        self.history = deque(maxlen=721)

    def add(self, trace, boundary):
        self.values.append(
            (dict(trace["stages"]), boundary, trace.get("error_ms"), time.monotonic())
        )
        durations = list(trace["stages"].values())
        if all(v is not None for v in durations):
            bucket = int(time.monotonic() // 5)
            if not self.history or self.history[-1][0] != bucket:
                self.history.append((bucket, array("d")))
            if len(self.history[-1][1]) < 5000:
                self.history[-1][1].append(sum(durations))

    def snapshot(self):
        return list(self.values), [(at, values[:]) for at, values in self.history]

    @staticmethod
    def report(values, history=()):
        if not values:
            return {}
        boundary = values[-1][1]
        values = [v for v in values if v[1] == boundary]
        names = [k for k in STAGES if any(k in v[0] for v in values)]
        complete = [v for v in values if all(n in v[0] and v[0][n] is not None for n in names)]
        missing = [n for n in names if values[-1][0].get(n) is None]
        history = [
            {
                "at": bucket * 5,
                **dict(
                    zip(
                        ("p50", "p95", "p99", "p99_9"),
                        map(float, np.percentile(totals, [50, 95, 99, 99.9])),
                        strict=True,
                    )
                ),
            }
            for bucket, totals in history
        ]
        result = {
            "boundary": boundary,
            "count": len(complete),
            "sampled": len(values),
            "missing": missing,
            "stages": {},
            "total": {},
            "history": history,
            "history_end": time.monotonic(),
        }
        # Never keep displaying an old complete total after a clock loses accuracy.
        if missing or not complete:
            result["partial"] = {}
            for name in names:
                measured = [v[0][name] for v in values if v[0].get(name) is not None]
                if measured:
                    result["partial"][name] = dict(
                        zip(
                            ("p50", "p95", "p99", "p99_9"),
                            map(float, np.percentile(measured, [50, 95, 99, 99.9])),
                            strict=True,
                        )
                    )
            return result
        matrix = np.array([[v[0][n] for n in names] for v in complete])
        matrix = matrix[np.argsort(matrix.sum(axis=1), kind="stable")]
        ranks = np.array([0.5, 0.95, 0.99, 0.999]) * (len(matrix) - 1)
        lower, upper = np.floor(ranks).astype(int), np.ceil(ranks).astype(int)
        weight = (ranks - lower)[:, None]
        columns = matrix[lower] * (1 - weight) + matrix[upper] * weight
        keys = ("p50", "p95", "p99", "p99_9")
        for i, name in enumerate(names):
            result["stages"][name] = dict(zip(keys, map(float, columns[:, i]), strict=True))
        result["total"] = dict(zip(keys, map(float, columns.sum(axis=1)), strict=True))
        result["error_ms"] = max(v[2] or 0 for v in complete)
        return result
