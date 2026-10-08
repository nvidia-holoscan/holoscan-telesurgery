# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the installed Holoscan scheduler, including bounded request expiry."""

import time

import pytest

pytest.importorskip("holoscan", exc_type=ImportError)
from telesurgery_runtime.application.pipeline import Executor  # noqa: E402

pytestmark = pytest.mark.sdk


def test_calls_are_not_dropped_and_failures_do_not_stop_the_graph():
    endpoint = Executor("requests")
    endpoint.start()
    try:
        pending = [endpoint.submit(lambda value: value * value, i) for i in range(20)]
        assert [future.result(timeout=3) for future in pending] == [i * i for i in range(20)]
        with pytest.raises(ZeroDivisionError):
            endpoint.submit(lambda: 1 / 0).result(timeout=3)
        slow = endpoint.submit(time.sleep, 0.08)
        stale = endpoint.submit(lambda: pytest.fail("Expired input executed"), timeout=0.001)
        slow.result(timeout=3)
        with pytest.raises(TimeoutError):
            stale.result(timeout=3)
        assert endpoint.submit(lambda: "alive").result(timeout=3) == "alive"
    finally:
        endpoint.close()
    with pytest.raises(RuntimeError, match="not running"):
        endpoint.submit(lambda: None).result()
