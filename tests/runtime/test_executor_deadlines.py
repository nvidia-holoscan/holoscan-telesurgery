# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stalled invocations must not extend request lifetime or allow concurrent calls."""

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from telesurgery.server.application import Application
from telesurgery_runtime.application.pipeline import Calls, Complete, Invoke


def test_stalled_invocation_expires_queued_work_without_releasing_active_slot():
    source = Calls()
    active, expired = Future(), Future()
    active.set_running_or_notify_cancel()
    source.active = active
    source.pending.put((expired, 0, lambda: pytest.fail("Stale input ran"), ()))
    assert source.compute() is None
    with pytest.raises(TimeoutError, match="expired"):
        expired.result()
    assert source.active is active and not active.done()
    assert source.compute() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [False, True])
async def test_caller_timeout_cancels_only_queued_work(running):
    future = Future()
    if running:
        future.set_running_or_notify_cancel()
    app = SimpleNamespace(engine=SimpleNamespace(submit=lambda *args, **kwargs: future))
    with pytest.raises(TimeoutError):
        await Application.run(app, lambda: None, timeout=0.01)
    if running:
        assert future.running() and not future.done()
        Complete().compute((future, True, None))
        assert future.result() is True
    else:
        assert future.cancelled()
        assert (
            Invoke().compute((future, float("inf"), lambda: pytest.fail("Cancelled call ran"), ()))
            is None
        )
    await asyncio.sleep(0)
