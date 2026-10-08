# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Diagnostics stay opt-in and percentile aggregation stays off the service loop."""

import asyncio
import json
import threading

import pytest
from aiohttp import ClientSession, web
from telesurgery.server.application import Application
from telesurgery.server.http import create_app
from telesurgery.server.media import Media
from telesurgery_core.transport.protocol import VideoHeader


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_metrics_are_opt_in_and_aggregated_in_worker(tmp_path, monkeypatch):
    service = Application("surgeon", tmp_path)
    main_thread = threading.get_ident()
    reports = []

    def statistics():
        assert threading.get_ident() != main_thread
        reports.append(True)
        return {"camera": {"frames": 30}}

    monkeypatch.setattr(service.media, "statistics", statistics)
    app = create_app(service)
    app.cleanup_ctx.clear()  # This test exercises HTTP reporting, without a device graph.
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://localhost:{site._server.sockets[0].getsockname()[1]}/api/status"
    try:
        async with ClientSession() as client:
            async with client.get(url) as response:
                assert "video" not in await response.json()
            assert not reports
            async with client.get(url + "?metrics=1") as response:
                assert (await response.json())["video"]["camera"]["frames"] == 30
                assert response.headers["Cache-Control"] == "no-store"
            assert len(reports) == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_video_age_is_local_arrival_age():
    media = Media()
    # An unrelated source clock must not turn into an apparent transit delay.
    header = json.loads(VideoHeader(0, 1, 100, 100, encode_ns=2_000_000).encode())
    await media.put("camera", header, b"encoded")
    await asyncio.sleep(0.01)
    report = (await asyncio.to_thread(media.statistics))["camera"]
    assert 10 <= report["last_frame_age_ms"] < 1000
    assert report["metrics"]["encode_ms"]["p50"] == 2


@pytest.mark.sdk
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["patient", "surgeon"])
async def test_reset_preserves_stream_and_selection(tmp_path, role):
    service = Application(role, tmp_path)
    service.selected.add("camera")
    header = json.loads(VideoHeader(100, 1, 100, 100, encode_ns=2_000_000).encode())
    await service.media.put("camera", header, b"encoded")
    feed = service.media.feeds["camera"]
    packet, revision = feed.packet, feed.revision
    await service.action("metrics.reset", {})
    assert service.selected == {"camera"}
    assert feed.packet is packet and feed.revision == revision
    assert feed.benchmark.report()["frames"] == 0
    header["sequence"] = 101
    await service.media.put("camera", header, b"encoded")
    report = feed.benchmark.report()
    assert report["frames"] == 1 and report["sequence_gaps"] == 0
    assert report["metrics"]["encode_ms"]["count"] == 1


@pytest.mark.sdk
@pytest.mark.asyncio
async def test_stream_metrics_and_reset_leave_other_streams_alone(tmp_path):
    service = Application("surgeon", tmp_path)
    header = json.loads(VideoHeader(0, 1, 100, 100, encode_ns=2_000_000).encode())
    for camera in ("one", "two"):
        await service.media.put(camera, header, b"encoded")
    report = await service.status(metrics=True, device="one")
    assert list(report["video"]) == ["one"]
    await service.action("metrics.reset", {"device": "one"})
    assert service.media.feeds["one"].benchmark.report()["frames"] == 0
    assert service.media.feeds["two"].benchmark.report()["frames"] == 1
