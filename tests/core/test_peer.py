# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bound half-open connections without expiring healthy idle endpoints."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from telesurgery_core.transport.peer import PREFIX, Peer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "partial", [b"", b"\x00", PREFIX.pack(20, 0) + b"{", PREFIX.pack(2, 20) + b"{}x"]
)
async def test_silent_or_incomplete_message_closes_peer(monkeypatch, partial):
    monkeypatch.setattr("telesurgery_core.transport.peer.RECEIVE_TIMEOUT", 0.2)
    connected = asyncio.Future()
    handler = AsyncMock()

    async def accept(reader, writer):
        connected.set_result(Peer(reader, writer, handler).start())

    async with await asyncio.start_server(accept, "127.0.0.1", 0) as server:
        _, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        peer = await connected
        try:
            writer.write(partial)
            await writer.drain()
            # A rebooted client leaves no FIN, and never answers this request.
            with pytest.raises(ConnectionError, match="disconnected"):
                await peer.call("status", timeout=2)
            assert peer.closed.is_set()
            handler.assert_not_awaited()
        finally:
            writer.close()
            await writer.wait_closed()
            await peer.close()
        assert peer.prober.done() and peer.sender.done() and peer.receiver.done()


@pytest.mark.asyncio
async def test_shared_clock_idle_peers_keep_alive_and_still_answer_rpc(monkeypatch):
    monkeypatch.setattr("telesurgery_core.transport.peer.RECEIVE_TIMEOUT", 0.3)
    monkeypatch.setattr("telesurgery_core.transport.peer.PROBE_INTERVAL", 0.03)
    connected = asyncio.Future()
    handler = AsyncMock(return_value={"ok": True})

    async def accept(reader, writer):
        connected.set_result(Peer(reader, writer, handler).start())

    async with await asyncio.start_server(accept, "127.0.0.1", 0) as server:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", server.sockets[0].getsockname()[1]
        )
        local = Peer(reader, writer, handler).start()
        remote = await connected
        try:
            await asyncio.sleep(0.7)
            assert local.relative_clock.domain == remote.relative_clock.domain == local.clock.domain
            assert not local.closed.is_set() and not remote.closed.is_set()
            handler.assert_not_awaited()
            assert await local.call("status") == {"ok": True}
            handler.assert_awaited_once()
        finally:
            await local.close()
            await remote.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), object()])
async def test_invalid_local_message_does_not_disconnect_other_requests(value):
    connected = asyncio.Future()

    async def handler(peer, method, params):
        return {"bad": value} if method == "bad_response" else {"ok": True}

    async def accept(reader, writer):
        connected.set_result(Peer(reader, writer, handler).start())

    async with await asyncio.start_server(accept, "127.0.0.1", 0) as server:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", server.sockets[0].getsockname()[1]
        )
        local = Peer(reader, writer, handler).start()
        remote = await connected
        try:
            with pytest.raises(ValueError, match="Invalid application message"):
                await local.call("robot.move", {"command": {"joints": [value]}})
            with pytest.raises(RuntimeError, match="Invalid response data"):
                await local.call("bad_response")
            assert await local.call("status") == {"ok": True}
            assert not local.closed.is_set() and not remote.closed.is_set()
        finally:
            await local.close()
            await remote.close()
