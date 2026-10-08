# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard binding must preserve same-origin request checks."""

import ssl
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from telesurgery.server.http import create_app
from telesurgery.server.security import dashboard_tls


@pytest.mark.asyncio
@pytest.mark.parametrize("host", [None, "localhost", "::1", "0.0.0.0", "10.0.0.2"])
async def test_dashboard_access(host):
    service = SimpleNamespace(action=AsyncMock(return_value="ok"))
    app = create_app(service) if host is None else create_app(service, host)
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as client:
        # A network binding accepts the browser's address; localhost defaults
        # also reject foreign Host headers (including DNS rebinding attempts).
        network = host in {"0.0.0.0", "10.0.0.2"}
        for authority, accepted in [("127.0.0.1:8000", True), ("room.example:8000", network)]:
            response = await client.post(
                "/api/action",
                json={"action": "test"},
                headers={"Host": authority, "Origin": f"http://{authority}"},
            )
            assert response.status == (200 if accepted else 403)

        authority = "room.example:8000" if network else "[::1]:8000"
        for origin in ["http://elsewhere.example:8000", f"https://{authority}", "null"]:
            response = await client.post(
                "/api/action",
                json={"action": "test"},
                headers={"Host": authority, "Origin": origin},
            )
            assert response.status == 403
        response = await client.post(
            "/api/action", data={"action": "test"}, headers={"Host": authority}
        )
        assert response.status == 415
        assert service.action.await_count == (2 if network else 1)

        # Read-only browser requests normally omit Origin.
        response = await client.get("/", headers={"Host": authority})
        assert response.status == 200
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "script-src 'self'" in response.headers["Content-Security-Policy"]
        assert "Server" not in response.headers


@pytest.mark.asyncio
async def test_invalid_requests_cannot_reach_actions():
    service = SimpleNamespace(action=AsyncMock())
    app = create_app(service)
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as client:
        for path in ("/api/action", "/api/offer"):
            for body in [None, [], "text", {}, {"action": "test", "params": []}]:
                response = await client.post(path, json=body)
                assert response.status in {400, 415}
                assert response.headers["Cache-Control"] == "no-store"
            response = await client.post(
                path, data="{" * 131073, headers={"Content-Type": "application/json"}
            )
            assert response.status == 413
        response = await client.get("/", headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status == 403
        assert response.headers["X-Frame-Options"] == "DENY"
        assert (await client.get("/static/../../pyproject.toml")).status == 404
        service.action.assert_not_awaited()


@pytest.mark.asyncio
async def test_dashboard_https_generated_and_supplied_certificates(tmp_path):
    from cryptography import x509

    generated = dashboard_tls(tmp_path, "127.0.0.1")
    cert, key = tmp_path / "https/endpoint.pem", tmp_path / "https/endpoint.key"
    original = cert.read_bytes()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    parsed = x509.load_pem_x509_certificate(original)
    assert parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    trusted = ssl.create_default_context(cafile=str(cert))
    for context in [generated, dashboard_tls(tmp_path, "127.0.0.1", cert, key)]:
        app = create_app(SimpleNamespace(action=AsyncMock(return_value=True)))
        app.cleanup_ctx.clear()
        server = TestServer(app)
        await server.start_server(ssl=context)
        async with TestClient(server) as client:
            origin = str(client.make_url("/")).rstrip("/")
            assert origin.startswith("https://")
            response = await client.post(
                "/api/action", json={"action": "test"}, headers={"Origin": origin}, ssl=trusted
            )
            assert response.status == 200
            response = await client.post(
                "/api/action",
                json={"action": "test"},
                headers={"Origin": origin.replace("https:", "http:")},
                ssl=trusted,
            )
            assert response.status == 403
    dashboard_tls(tmp_path, "127.0.0.1")
    assert cert.read_bytes() == original
