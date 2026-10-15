# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Recognize HSB announcements without importing either capture runtime."""

import ipaddress
import socket
import time


def board_address(packet, peer):
    """Validate the BOOTP vendor envelope used by the public sensor bridge."""
    # BOOTP header, server name and boot file occupy 236 bytes. HSB appends
    # vendor option E0, length, 'NVDA', data plane and enumeration version.
    if (
        len(packet) < 277
        or packet[:3] != b"\x01\x01\x06"
        or packet[236] != 0xE0
        or packet[237] < 39
        or len(packet) < 238 + packet[237]
        or packet[238:242] != b"NVDA"
        or packet[243] not in (1, 2)
    ):
        return None
    address = ipaddress.IPv4Address(peer)
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        return None
    return str(address)


def discover(timeout=0.5, *, first=False):
    """Passively listen to board broadcasts; never probe or reset a camera."""
    addresses = set()
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        # Match the vendor listener so concurrent discovery/capture can coexist.
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        receiver.bind(("", 12267))
        while (remaining := deadline - time.monotonic()) > 0:
            receiver.settimeout(remaining)
            try:
                packet, peer = receiver.recvfrom(2048)
            except TimeoutError:
                break
            address = board_address(packet, peer[0])
            if address:
                addresses.add(address)
                if first:
                    break
    return {address: ["linux"] for address in sorted(addresses)}


def configured(directory):
    """Recognize manual cameras and previously configured discovered streams."""
    from telesurgery_core.configuration import load

    devices = load(directory / "devices.yaml")
    cameras = devices.get("cameras", [])
    if not isinstance(cameras, list) or any(not isinstance(item, dict) for item in cameras):
        raise ValueError(f"Expected a cameras list in {directory / 'devices.yaml'}")
    if any(item.get("source") == "imx274" or item.get("kind") == "HSB" for item in cameras):
        return True
    return any(
        isinstance(key, str) and key.startswith("hsb-") for key in load(directory / "streams.yaml")
    )
