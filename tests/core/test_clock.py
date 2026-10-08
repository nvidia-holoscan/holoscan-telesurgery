# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Clock uncertainty must never become an apparently precise network latency."""

import time

import pytest
from telesurgery_core.diagnostics.clock import Clock, tracking

TRACKING = """Reference ID : C0000201 (192.0.2.1)
Stratum : 2
System time : 0.000010 seconds slow of NTP time
Root delay : 0.000200 seconds
Root dispersion : 0.000020 seconds
Skew : 0.100 ppm
Leap status : Normal
"""


def test_chrony_error_bound_and_untrusted_references():
    source, error, skew = tracking(TRACKING)
    assert source == "C0000201 (192.0.2.1)"
    assert error == pytest.approx(0.13) and skew == 0.1
    for text in (
        TRACKING.replace("Normal", "Not synchronised"),
        TRACKING.replace("C0000201", "7F7F0101"),
        TRACKING.replace("0.000200", "nan"),
    ):
        with pytest.raises(ValueError):
            tracking(text)


def test_same_host_uses_monotonic_clock_despite_wrong_wall_time():
    clock = Clock()
    clock.domain = "same-kernel-and-time-namespace"
    sent = clock.stamp()
    sent["wall_ns"] = 1
    sent["mono_ns"] -= 2_000_000
    timing = clock.delivery(sent)
    assert timing["delivery_ms"] >= 2 and timing["error_ms"] == 0


def test_remote_clock_quality_age_and_steps():
    clock = Clock()
    clock.quality = ("fixture", 0.1, 0, time.monotonic_ns(), time.time_ns())
    sent = {"domain": "other", "wall_ns": time.time_ns() - 5_000_000, "error_ms": 0.2}
    measured = clock.delivery(sent)
    assert measured["status"] == "Synchronized UTC clocks"
    assert measured["delivery_ms"] >= 5
    assert 0.3 <= measured["error_ms"] < 0.4
    for error in (None, -1, float("nan"), 2):
        assert "delivery_ms" not in clock.delivery({**sent, "error_ms": error})
    assert "delivery_ms" not in clock.delivery({**sent, "wall_ns": time.time_ns() + 1_000_000})
    clock.quality = ("fixture", 0.1, 0, time.monotonic_ns() - 20_000_000_000, time.time_ns())
    assert "delivery_ms" not in clock.delivery(sent)
    clock.quality = ("fixture", 0.1, 0, time.monotonic_ns(), time.time_ns() - 1_000_000_000)
    assert "delivery_ms" not in clock.delivery(sent)


def test_relative_clock_handles_offset_asymmetry_staleness_and_domain_changes(monkeypatch):
    from telesurgery_core.diagnostics.clock import PeerClock

    clock, remote = Clock(), PeerClock()
    now = 10_000_000_000
    monkeypatch.setattr(time, "monotonic_ns", lambda: now)
    # Remote clock is 3 seconds ahead. Asymmetric delays: 1 ms out, 3 ms back.
    remote.observe(
        "remote",
        now - 4_100_000,
        now + 3_000_000_000 - 3_100_000,
        now + 3_000_000_000 - 3_000_000,
        now,
    )
    sent = {"domain": "remote", "mono_ns": now + 3_000_000_000 - 6_000_000}
    measured = remote.delivery(clock, sent)
    assert measured["status"] == "Relative clock estimate"
    assert abs(measured["delivery_ms"] - 6) <= measured["error_ms"]
    assert measured["error_ms"] == pytest.approx(2)
    # Unknown wall clocks are irrelevant, but stale or unrelated samples are unusable.
    assert "delivery_ms" not in remote.delivery(clock, {**sent, "domain": "other"})
    now += 16_000_000_000
    assert "delivery_ms" not in remote.delivery(clock, sent)
    remote.observe("restarted", now - 2_000_000, now - 1_000_000, now - 1_000_000, now)
    assert len(remote.samples) == 1
    for bad in (None, -1, float("nan")):
        remote.observe("restarted", bad, now, now, now)
    assert len(remote.samples) == 1


@pytest.mark.asyncio
async def test_peer_clock_probes_bypass_device_commands_and_stop_on_close():
    import asyncio

    from telesurgery_core.transport.peer import Peer

    connected = asyncio.Future()

    async def reject(*args):
        raise AssertionError("Clock probes must not invoke device handlers")

    async def accept(reader, writer):
        clock = Clock()
        clock.domain = "remote-fixture"
        connected.set_result(Peer(reader, writer, reject, clock=clock).start())

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
    local = Peer(reader, writer, reject).start()
    remote = await connected
    try:
        async with asyncio.timeout(3):
            while not local.relative_clock.samples:
                await asyncio.sleep(0.01)
        sent = remote.clock.stamp()
        sent["mono_ns"] -= 5_000_000
        assert local.delivery(sent)["delivery_ms"] >= 4
    finally:
        await local.close()
        await remote.close()
        server.close()
        await server.wait_closed()
    assert local.prober.done() and remote.prober.done()
