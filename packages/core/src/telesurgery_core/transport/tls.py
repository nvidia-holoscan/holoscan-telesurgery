# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Local application certificates and pinned peer identities; no account service."""

import datetime
import hashlib
import ipaddress
import os
import ssl


def server_context(directory, *, hosts=()):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_file, cert_file = directory / "endpoint.key", directory / "endpoint.pem"
    if not key_file.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Holoscan Telesurgery")])
        now = datetime.datetime.now(datetime.UTC)
        builder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=365 if hosts else 3650))
        )
        if hosts:
            names = []
            for host in hosts:
                try:
                    names.append(x509.IPAddress(ipaddress.ip_address(host)))
                except ValueError:
                    names.append(x509.DNSName(host))
            builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
        cert = builder.sign(key, hashes.SHA256())
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(cert_file, key_file)
    return context


def client_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    return context


def pin_peer(writer, address, directory, expected=None):
    certificate = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    fingerprint = hashlib.sha256(certificate).hexdigest()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    from telesurgery_core.configuration import load, save

    path = directory / "peers.yaml"
    peers = load(path)
    known = expected or peers.get(address)
    if known and known != fingerprint:
        raise PermissionError("Patient endpoint identity changed; reconnect to a verified endpoint")
    if address not in peers:
        peers[address] = fingerprint
        save(path, peers)
    return fingerprint
