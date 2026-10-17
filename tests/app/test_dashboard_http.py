# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard binding must preserve same-origin request checks."""

import asyncio
import ssl
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from telesurgery.server.http import create_app
from telesurgery.server.security import dashboard_client_host, dashboard_tls
from telesurgery_core.transport.tls import server_context


@pytest.mark.parametrize("role", ["patient", "surgeon"])
def test_cli_refuses_network_http_without_explicit_override(role, capsys):
    from telesurgery.application.cli import main

    with pytest.raises(SystemExit) as error:
        main([role, "--host", "0.0.0.0"])
    assert error.value.code == 2
    assert "require --ssl or explicit --insecure" in capsys.readouterr().err


@pytest.mark.asyncio
@pytest.mark.parametrize("host", [None, "localhost", "::1", "0.0.0.0", "10.0.0.2"])
async def test_dashboard_access(host):
    service = SimpleNamespace(action=AsyncMock(return_value="ok"))
    app = create_app(service) if host is None else create_app(service, host, token="test-code")
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app), headers={"Authorization": "Bearer test-code"}) as client:
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
@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
async def test_nonfinite_json_is_rejected_before_action(number):
    service = SimpleNamespace(action=AsyncMock(return_value=True))
    app = create_app(service)
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/action",
            data='{"action":"robot.move","params":{"command":{"joints":[' + number + "]}}}",
            headers={"Content-Type": "application/json"},
        )
        assert response.status == 400
        assert "finite" in (await response.json())["error"]
        service.action.assert_not_awaited()
        assert (await client.post("/api/action", json={"action": "status"})).status == 200


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


@pytest.mark.asyncio
async def test_native_https_uses_custom_certificate_local_name_and_verifies_identity(tmp_path):
    from telesurgery.controller.client import Client

    context = server_context(tmp_path, hosts=["localhost"])
    certificate = tmp_path / "endpoint.pem"
    host = dashboard_client_host("0.0.0.0", certificate)
    assert host == "localhost"
    app = create_app(SimpleNamespace(action=AsyncMock(return_value=True)))
    app.cleanup_ctx.clear()
    server = TestServer(app)
    await server.start_server(ssl=context)
    try:
        client = Client(f"https://{host}:{server.port}", str(certificate))
        assert await asyncio.to_thread(client.action, "test", {}) is True
        wrong_name = Client(f"https://127.0.0.1:{server.port}", str(certificate))
        with pytest.raises(RuntimeError, match="certificate for 127.0.0.1"):
            await asyncio.to_thread(wrong_name.action, "test", {})
    finally:
        await server.close()


@pytest.mark.parametrize("bind,expected", [("0.0.0.0", "127.0.0.1"), ("::", "::1")])
def test_native_wildcard_url_uses_matching_loopback_family(bind, expected):
    assert dashboard_client_host(bind) == expected


def test_native_custom_certificate_does_not_redirect_to_a_remote_host(tmp_path, monkeypatch):
    from telesurgery.server import security

    server_context(tmp_path, hosts=["external.example"])
    monkeypatch.setattr(security.ifaddr, "get_adapters", lambda: [])
    monkeypatch.setattr(
        security.socket, "getaddrinfo", lambda *args: [(2, 1, 6, "", ("192.0.2.1", 0))]
    )
    assert dashboard_client_host("0.0.0.0", tmp_path / "endpoint.pem") == "127.0.0.1"


@pytest.mark.asyncio
async def test_network_dashboard_requires_launch_code_for_all_api_routes():
    service = SimpleNamespace(action=AsyncMock(return_value=True))
    app = create_app(service, "0.0.0.0", token="first-launch")
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as client:
        assert "Open this dashboard" in await (await client.get("/")).text()
        for route in ("/api/status", "/api/nodes/node/log", "/api/robots/robot/log"):
            assert (await client.get(route)).status == 401
        for route in ("/api/action", "/api/offer"):
            assert (await client.post(route, json={})).status == 401
        assert (await client.post("/api/login", json={"token": "old-launch"})).status == 401
        assert (
            await client.post(
                "/api/login",
                json={"token": "first-launch"},
                headers={"Origin": "https://evil.invalid"},
            )
        ).status == 403
        response = await client.post("/api/login", json={"token": "first-launch"})
        assert response.status == 200
        cookie = response.cookies[f"telesurgery_access_{client.port}"]
        assert cookie["httponly"]
        assert cookie["samesite"] == "Strict"
        assert (await client.post("/api/action", json={"action": "status"})).status == 200
        assert "access-form" not in await (await client.get("/")).text()


@pytest.mark.asyncio
async def test_patient_and_surgeon_cookies_do_not_replace_each_other():
    from aiohttp import CookieJar

    jar = CookieJar(unsafe=True)
    apps = [
        create_app(SimpleNamespace(action=AsyncMock(return_value=True)), "0.0.0.0", token=code)
        for code in ("patient-code", "surgeon-code")
    ]
    for app in apps:
        app.cleanup_ctx.clear()
    async with (
        TestClient(TestServer(apps[0]), cookie_jar=jar) as patient,
        TestClient(TestServer(apps[1]), cookie_jar=jar) as surgeon,
    ):
        for client, code in ((patient, "patient-code"), (surgeon, "surgeon-code")):
            assert (await client.post("/api/login", json={"token": code})).status == 200
        for client in (patient, surgeon):
            assert (await client.post("/api/action", json={"action": "test"})).status == 200


@pytest.mark.asyncio
async def test_native_client_authenticates_without_putting_code_in_url():
    from telesurgery.controller.client import Client

    app = create_app(
        SimpleNamespace(action=AsyncMock(return_value=True)), "0.0.0.0", token="launch-code"
    )
    app.cleanup_ctx.clear()
    async with TestClient(TestServer(app)) as browser:
        client = Client(str(browser.make_url("/")), token="launch-code")
        assert await asyncio.to_thread(client.action, "test", {}) is True
        with pytest.raises(RuntimeError, match="access code"):
            await asyncio.to_thread(Client(client.server).action, "test", {})
