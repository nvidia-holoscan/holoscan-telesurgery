# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read clock quality without adjusting clocks or probing the video connection."""

import asyncio
import math
import os
import subprocess
import time
from collections import deque
from pathlib import Path

# Do not present a millisecond-scale latency when clocks cannot resolve it.
MAX_ERROR_MS = 1.0


def tracking(text):
    fields = dict(line.split(":", 1) for line in text.splitlines() if ":" in line)
    fields = {key.strip(): value.strip() for key, value in fields.items()}
    if fields.get("Leap status") != "Normal" or not 1 <= int(fields["Stratum"]) <= 15:
        raise ValueError("Chrony is not synchronized")
    source = fields["Reference ID"]
    if source.startswith("7F7F0101"):
        raise ValueError("Chrony local mode does not establish UTC accuracy")
    offset, delay, dispersion, skew = (
        float(fields[key].split()[0])
        for key in ("System time", "Root delay", "Root dispersion", "Skew")
    )
    if not all(math.isfinite(v) for v in (offset, delay, dispersion, skew)):
        raise ValueError("Invalid clock quality")
    if min(delay, dispersion, skew) < 0:
        raise ValueError("Invalid clock quality")
    return source, 1000 * (abs(offset) + delay / 2 + dispersion), skew


class Clock:
    def __init__(self):
        try:
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            self.domain = boot + "/" + os.readlink("/proc/self/ns/time")
        except OSError:
            self.domain = None
        self.quality = None
        self.reason = "Chrony tracking unavailable"

    async def watch(self):
        while True:
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["chronyc", "-n", "tracking"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=True,
                    env={**os.environ, "LC_ALL": "C"},
                )
                source, error, skew = tracking(result.stdout)
                self.quality = (source, error, skew, time.monotonic_ns(), time.time_ns())
            except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
                self.quality = None
                self.reason = (
                    "Chrony tracking unavailable" if not isinstance(exc, ValueError) else str(exc)
                )
            await asyncio.sleep(5)

    def status(self):
        if self.quality:
            source, error, skew, mono, wall = self.quality
            elapsed = (time.monotonic_ns() - mono) / 1e9
            adjustment = abs((time.time_ns() - wall) / 1e9 - elapsed) * 1000
            if 0 <= elapsed < 15:
                return {
                    "state": "synchronized",
                    "source": source,
                    "error_ms": error + adjustment + elapsed * skew / 1000,
                }
        return {"state": "unavailable", "detail": self.reason, "error_ms": None}

    def stamp(self):
        return {
            "domain": self.domain,
            "mono_ns": time.monotonic_ns(),
            "wall_ns": time.time_ns(),
            "error_ms": self.status()["error_ms"],
        }

    def delivery(self, sent):
        now = self.stamp()
        result = {"received_ns": now["mono_ns"], "status": "Clock synchronization required"}
        if not isinstance(sent, dict):
            return result
        if self.domain and sent.get("domain") == self.domain:
            start, end, error = sent.get("mono_ns"), now["mono_ns"], 0
            status = "Same host · monotonic clock"
        else:
            bounds = (sent.get("error_ms"), now["error_ms"])
            if not all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in bounds):
                return result
            error = sum(bounds)
            result["error_ms"] = error
            result["status"] = "Insufficient clock accuracy"
            if error > MAX_ERROR_MS:
                return result
            start, end = sent.get("wall_ns"), now["wall_ns"]
            status = "Synchronized UTC clocks"
        if type(start) is not int or start <= 0:
            return result
        delay = (end - start) / 1e6
        if delay < error:
            result["status"] = "Insufficient clock accuracy"
            return result
        return {**result, "status": status, "delivery_ms": delay, "error_ms": error}


class PeerClock:
    """Relative monotonic-clock estimate from four timestamps, with RTT/2 uncertainty.

    This measures connection timing; it never sets the system clock. Keep recent
    probes and allow 1000 ppm relative drift (including kernel clock slewing).
    """

    def __init__(self):
        self.samples = deque(maxlen=16)
        self.domain = None

    def observe(self, domain, t0, t1, t2, t3):
        if not isinstance(domain, str) or not domain:
            return
        if any(type(v) is not int or v <= 0 for v in (t0, t1, t2, t3)):
            return
        rtt = (t3 - t0) - (t2 - t1)
        if t2 < t1 or rtt < 0 or t3 - t0 > 5_000_000_000:
            return
        if domain != self.domain:
            self.samples.clear()
            self.domain = domain
        offset = ((t1 - t0) + (t2 - t3)) / 2
        self.samples.append((t3, offset, rtt / 2))

    def delivery(self, clock, sent):
        result = clock.delivery(sent)
        if not isinstance(sent, dict) or sent.get("domain") != self.domain:
            return result
        now = result["received_ns"]
        samples = [
            (error + (now - at) * 0.001, offset)
            for at, offset, error in self.samples
            if 0 <= now - at < 15_000_000_000
        ]
        if not samples or type(sent.get("mono_ns")) is not int:
            return result
        error, offset = min(samples)
        error /= 1e6
        if "delivery_ms" in result and result["error_ms"] <= error:
            return result
        delay = (now - sent["mono_ns"] + offset) / 1e6
        if delay < 0:
            return result
        return {
            "received_ns": now,
            "delivery_ms": delay,
            "error_ms": error,
            "status": "Relative clock estimate",
        }
