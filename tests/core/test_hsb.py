# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bootstrap discovery must recognize actual HSB traffic without loading an SDK."""

import socket

import pytest
from telesurgery_core import hsb


def announcement(version=2):
    packet = bytearray(300)
    packet[:3] = b"\x01\x01\x06"
    packet[236:244] = bytes([0xE0, 56]) + b"NVDA" + bytes([0, version])
    return bytes(packet)


@pytest.mark.parametrize("version", [1, 2])
def test_recognize_public_board_announcement(version):
    assert hsb.board_address(announcement(version), "192.168.0.2") == "192.168.0.2"


@pytest.mark.parametrize(
    "packet,peer",
    [
        (b"", "192.168.0.2"),
        (announcement()[:250], "192.168.0.2"),
        (announcement().replace(b"NVDA", b"DHCP"), "192.168.0.2"),
        (announcement(3), "192.168.0.2"),
        (b"\x02" + announcement()[1:], "192.168.0.2"),
        (announcement(), "0.0.0.0"),
        (announcement(), "127.0.0.1"),
        (announcement(), "224.0.0.1"),
    ],
)
def test_unrelated_or_incomplete_packets_are_not_boards(packet, peer):
    assert hsb.board_address(packet, peer) is None


@pytest.mark.parametrize("first", [False, True])
def test_listener_is_passive_bounded_and_closes_after_discovery(monkeypatch, first):
    packets = iter([(b"unrelated", ("192.168.0.8", 123)), (announcement(), ("192.168.0.2", 12268))])

    class Receiver:
        closed = False
        options = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def setsockopt(self, *args):
            self.options.append(args)

        def bind(self, address):
            assert address == ("", 12267)

        def settimeout(self, timeout):
            assert 0 < timeout <= 0.5

        def recvfrom(self, size):
            assert size == 2048
            try:
                return next(packets)
            except StopIteration as exc:
                raise TimeoutError from exc

    receiver = Receiver()
    monkeypatch.setattr(hsb.socket, "socket", lambda *args: receiver)
    assert hsb.discover(first=first) == {"192.168.0.2": ["linux"]}
    assert receiver.closed
    assert (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in receiver.options
    assert (socket.SOL_SOCKET, socket.SO_REUSEPORT, 1) in receiver.options
