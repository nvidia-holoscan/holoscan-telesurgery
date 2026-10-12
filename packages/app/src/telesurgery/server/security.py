# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dashboard request boundaries, response headers and HTTPS certificates."""

import ipaddress
import logging
import socket
import ssl
from pathlib import Path

import ifaddr
from aiohttp import web
from cryptography import x509
from telesurgery_core.transport.tls import server_context


def dashboard_client_host(host, certificate=None):
    """Choose a local certificate identity when the dashboard binds every interface."""
    # Select a client address; this does not create a listener.
    if host not in {"0.0.0.0", "::"}:  # nosec B104
        return host
    loopback = "::1" if host == "::" else "127.0.0.1"
    if not certificate:
        return loopback
    parsed = x509.load_pem_x509_certificate(Path(certificate).read_bytes())
    try:
        names = parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return loopback  # The client reports the missing certificate identity.
    ips = names.get_values_for_type(x509.IPAddress)
    if ipaddress.ip_address(loopback) in ips:
        return loopback
    local = {"127.0.0.1", "::1"}
    for adapter in ifaddr.get_adapters():
        local.update(ip.ip if isinstance(ip.ip, str) else ip.ip[0] for ip in adapter.ips)
    version = 6 if host == "::" else 4
    for address in ips:
        if address.version == version and str(address) in local:
            return str(address)
    for name in names.get_values_for_type(x509.DNSName):
        if "*" in name:
            continue
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(name, None)}
        except socket.gaierror:
            continue
        if (
            addresses
            and addresses <= local
            and any(ipaddress.ip_address(address).version == version for address in addresses)
        ):
            return name
    return loopback


def dashboard_requests(host):
    try:
        local_only = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local_only = host.lower() == "localhost"

    @web.middleware
    async def check(request, handler):
        try:
            if local_only and request.url.host not in {"localhost", "127.0.0.1", "::1", host}:
                raise web.HTTPForbidden(text="Use the local dashboard address")
            origin = request.headers.get("Origin")
            if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
                origin and origin != f"{request.scheme}://{request.host}"
            ):
                raise web.HTTPForbidden(text="Cross-origin dashboard access is disabled")
            if request.method == "POST" and request.content_type != "application/json":
                raise web.HTTPUnsupportedMediaType(text="Expected application/json")
            return await handler(request)
        except (ValueError, KeyError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except PermissionError as exc:
            return web.json_response({"error": str(exc)}, status=403)
        except (RuntimeError, ConnectionError, OSError, TimeoutError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    return check


async def security_headers(request, response):
    response.headers.update(
        {
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; media-src 'self' blob:; "
                "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
        }
    )
    response.headers.pop("Server", None)
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"


def dashboard_tls(directory, host, cert=None, key=None):
    if cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(cert, key)
        return context
    hosts = {"localhost", "127.0.0.1", "::1", socket.gethostname(), socket.getfqdn()}
    # Wildcard bind addresses are not usable certificate identities.
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        hosts.add(host)
    else:
        if not address.is_unspecified:
            hosts.add(host)
    for adapter in ifaddr.get_adapters():
        hosts.update(ip.ip if isinstance(ip.ip, str) else ip.ip[0] for ip in adapter.ips)
    directory = directory / "https"
    context = server_context(directory, hosts=sorted(hosts))
    logging.getLogger(__name__).info(
        "Self-signed dashboard certificate: %s", directory / "endpoint.pem"
    )
    return context
