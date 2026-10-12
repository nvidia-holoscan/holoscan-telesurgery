# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Closing a native window removes its temporary connection credentials."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telesurgery.server.viewers import NativeViews


@pytest.mark.asyncio
async def test_natural_window_exit_cleans_credentials_and_can_reopen(tmp_path, monkeypatch):
    create_process = asyncio.create_subprocess_exec

    async def viewer(*args, **kwargs):
        return await create_process(
            sys.executable,
            "-c",
            "import sys,time; from pathlib import Path; p=Path(sys.argv[1]); "
            "p.with_name('status.json').write_text('{\"status\":\"running\"}'); "
            "\nwhile not p.with_name('finish').exists(): time.sleep(.01)",
            args[-1],
            **kwargs,
        )

    monkeypatch.setenv("DISPLAY", ":fixture")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", viewer)
    windows = NativeViews(tmp_path)
    try:
        for _ in range(2):
            await windows.open({"camera": "room"})
            window = windows.windows["room"]
            config = Path(window["config"])
            assert config.stat().st_mode & 0o777 == 0o600
            config.with_name("finish").touch()
            await asyncio.wait_for(window["process"].wait(), 3)
            assert windows.status()["room"]["status"] == "closed"
            assert not config.parent.exists()
            assert windows.status()["room"]["status"] == "closed"
    finally:
        await windows.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["close", "replace", "cancel"])
async def test_slow_startup_does_not_block_close_or_close_a_replacement(
    tmp_path, monkeypatch, operation
):
    processes = []

    async def viewer(*args, **kwargs):
        process = SimpleNamespace(returncode=None, wait=AsyncMock())

        def terminate():
            process.returncode = 0

        process.terminate = Mock(side_effect=terminate)
        processes.append(process)
        if len(processes) > 1:
            Path(args[-1]).with_name("status.json").write_text('{"status":"running"}')
        return process

    monkeypatch.setenv("DISPLAY", ":fixture")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", viewer)
    windows = NativeViews(tmp_path)
    opening = asyncio.create_task(windows.open({"camera": "room", "codec": "surgical-tokenizer"}))
    try:
        async with asyncio.timeout(1):
            while not windows.windows:
                await asyncio.sleep(0)
        config = windows.windows["room"]["config"]
        if operation == "replace":
            assert await asyncio.wait_for(windows.open({"camera": "room"}), 1)
        elif operation == "close":
            await asyncio.wait_for(windows.close(), 1)
        else:
            opening.cancel()
        expected = asyncio.CancelledError if operation == "cancel" else RuntimeError
        with pytest.raises(expected):
            await asyncio.wait_for(opening, 1)
        assert not config.parent.exists()
        processes[0].terminate.assert_called_once_with()
        if operation == "replace":
            assert windows.status()["room"]["status"] == "running"
            processes[1].terminate.assert_not_called()
    finally:
        opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)
        await windows.close()
