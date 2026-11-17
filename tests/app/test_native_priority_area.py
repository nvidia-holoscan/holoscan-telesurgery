# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A camera open in Holoviz learns its priority area and lends a still to draw on."""

import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from telesurgery.server.application import Application
from telesurgery.server.http import create_app
from telesurgery.server.viewers import NativeViews

BOX = [[0.3, 0.25], [0.7, 0.25], [0.7, 0.75], [0.3, 0.75]]
LASSO = [[0.2, 0.2], [0.6, 0.1], [0.8, 0.5], [0.4, 0.8]]


@pytest.fixture
def windows(tmp_path, monkeypatch):
    """Window supervisor whose viewer processes are stand-ins that report "running"."""
    processes = []

    async def viewer(*args, **kwargs):
        process = SimpleNamespace(returncode=None, wait=AsyncMock())
        process.terminate = Mock(side_effect=lambda: setattr(process, "returncode", 0))
        processes.append(process)
        Path(args[-1]).with_name("status.json").write_text('{"status":"running"}')
        return process

    monkeypatch.setenv("DISPLAY", ":fixture")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", viewer)
    views = NativeViews(tmp_path)
    views.processes = processes
    return views


def directory(views, camera):
    return views.windows[camera]["config"].parent


@pytest.mark.asyncio
async def test_window_starts_with_the_area_and_is_told_only_when_it_changes(windows):
    try:
        # An area chosen before Holoviz opened is part of the window's start-up settings.
        windows.regions({"room": BOX, "other": LASSO, "plain": None})
        await windows.open({"camera": "room"})
        await windows.open({"camera": "plain"})
        room, plain = directory(windows, "room"), directory(windows, "plain")
        assert json.loads((room / "config.json").read_text())["region"] == BOX
        assert json.loads((plain / "config.json").read_text())["region"] is None
        windows.regions({"room": BOX, "plain": None})
        assert not (room / "region.json").exists() and not (plain / "region.json").exists()

        windows.regions({"room": LASSO, "plain": None})
        assert json.loads((room / "region.json").read_text()) == {"points": LASSO}
        assert not (plain / "region.json").exists()
        # The same report again writes nothing: the window reads the file on every change.
        (room / "region.json").unlink()
        windows.regions({"room": LASSO, "plain": None})
        assert not (room / "region.json").exists()

        # Cleared by a surgeon, or no longer reported for the camera at all.
        windows.regions({"room": None, "plain": BOX})
        assert json.loads((room / "region.json").read_text()) == {"points": None}
        assert json.loads((plain / "region.json").read_text()) == {"points": BOX}
        windows.regions({})
        assert json.loads((plain / "region.json").read_text()) == {"points": None}

        # A window that has exited is left alone, and a new one starts with the area.
        windows.regions({"room": BOX})
        windows.processes[0].returncode = 0
        windows.regions({"room": LASSO})
        await windows.open({"camera": "room"})
        assert json.loads((directory(windows, "room") / "config.json").read_text())["region"] == (
            LASSO
        )
    finally:
        await windows.close()


@pytest.mark.asyncio
async def test_still_is_lent_only_by_a_running_window_and_only_while_fresh(windows):
    try:
        with pytest.raises(LookupError, match="not open in Holoviz"):
            windows.preview("room")
        await windows.open({"camera": "room"})
        folder = directory(windows, "room")
        request, still = folder / "preview-request", folder / "preview.jpg"
        # The first call asks the window for stills; there is none to return yet.
        assert windows.preview("room") is None
        assert request.exists()
        os.utime(request, (time.time() - 60,) * 2)
        still.write_bytes(b"jpeg bytes")
        assert windows.preview("room") == b"jpeg bytes"
        assert time.time() - request.stat().st_mtime < 2  # every call renews the request
        # A still left from an earlier request is not shown as the current picture.
        os.utime(still, (time.time() - 10,) * 2)
        assert windows.preview("room") is None
        with pytest.raises(LookupError):
            windows.preview("elsewhere")
        # A window that is still starting, or has closed, lends nothing.
        (folder / "status.json").write_text('{"status":"starting"}')
        with pytest.raises(LookupError):
            windows.preview("room")
        (folder / "status.json").write_text('{"status":"running"}')
        await windows.close("room")
        with pytest.raises(LookupError):
            windows.preview("room")
    finally:
        await windows.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
async def test_still_endpoint_serves_this_dashboards_holoviz_cameras_to_signed_in_users(
    windows, host
):
    try:
        await windows.open({"camera": "room:wide"})
        folder = directory(windows, "room:wide")
        app = create_app(SimpleNamespace(native=windows), host, token="launch-code")
        app.cleanup_ctx.clear()
        async with TestClient(TestServer(app)) as client:
            route = "/api/cameras/room%3Awide/native-preview"
            headers = {"Authorization": "Bearer launch-code"}
            if host == "0.0.0.0":
                # A network dashboard needs its launch code for stills like any other route.
                assert (await client.get(route)).status == 401
                assert not (folder / "preview-request").exists()
            response = await client.get(route, headers=headers)
            assert response.status == 204  # asked, nothing lent yet
            assert response.headers["Cache-Control"] == "no-store"
            assert (folder / "preview-request").exists()
            (folder / "preview.jpg").write_bytes(b"\xff\xd8 still \xff\xd9")
            response = await client.get(route, headers=headers)
            assert response.status == 200
            assert response.content_type == "image/jpeg"
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert await response.read() == b"\xff\xd8 still \xff\xd9"
            # Cameras this dashboard does not have open in Holoviz, and other sites.
            assert (
                await client.get("/api/cameras/room%3Ascope/native-preview", headers=headers)
            ).status == 404
            response = await client.get(
                route, headers={**headers, "Origin": "https://elsewhere.example"}
            )
            assert response.status == 403
    finally:
        await windows.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["patient", "surgeon"])
async def test_service_passes_reported_areas_to_its_holoviz_windows(tmp_path, monkeypatch, role):
    service = Application(role, tmp_path / role, endpoint_port=0)
    service.native.regions = Mock()
    cameras = [
        {"id": "room:scope", "region_supported": True, "region": BOX},
        {"id": "room:wide", "region_supported": True, "region": None},
        # An encoder without support reports nothing a window should draw.
        {"id": "room:old", "region_supported": False, "region": BOX},
    ]
    if role == "patient":
        monkeypatch.setattr(service, "inventory", lambda: {"cameras": cameras})
    else:
        service.remote_status = {"status": "approved", "cameras": cameras}
    service._native_areas()
    service.native.regions.assert_called_once_with({"room:scope": BOX, "room:wide": None})
