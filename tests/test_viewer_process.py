# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Closing a native window removes its temporary connection credentials."""

import asyncio
import sys
from pathlib import Path

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
