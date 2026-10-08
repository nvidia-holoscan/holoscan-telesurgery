# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Endpoint addresses and certificate identities."""

import hashlib
import ssl
from urllib.parse import urlsplit


def fingerprint(directory):
    cert = ssl.PEM_cert_to_DER_cert((directory / "endpoint.pem").read_text())
    return hashlib.sha256(cert).hexdigest()


def endpoint(address, default_port=7447):
    if not isinstance(address, str):
        raise ValueError("Enter a hostname or IP address")
    address = address.strip()
    if not address or any(c.isspace() for c in address):
        raise ValueError(f"Use an address such as 192.168.1.20:{default_port}")
    parsed = urlsplit("//" + address)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use a hostname or IP address, optionally followed by a port")
    port = default_port if parsed.port is None else parsed.port
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    host = parsed.hostname
    return host, port, f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
