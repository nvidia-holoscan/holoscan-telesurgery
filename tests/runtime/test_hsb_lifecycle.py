# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise nested SDK sessions without requiring an HSB board."""

import sys
import time
from types import SimpleNamespace

import pytest

hs = pytest.importorskip("holoscan", exc_type=ImportError)
pytestmark = [pytest.mark.sdk, pytest.mark.gpu]
if not hs.__version__.startswith("5."):
    pytest.skip("SDK 5 nested native lifecycle", allow_module_level=True)


@pytest.mark.parametrize("receiver", ["auto", "linux", "fusa"])
def test_native_camera_session_is_joined_outside_sdk_callbacks(monkeypatch, receiver):
    from telesurgery_core.video.config import Config
    from telesurgery_runtime.backends.sdk import ApplicationSession
    from telesurgery_runtime.backends.sdk5.camera import Imx274Camera
    from telesurgery_runtime.backends.sdk5.operators import PeriodicOp

    stopped = []

    class Tick(PeriodicOp):
        def compute(self, context):
            pass

    class NativeCapture:
        bayer_format = 0

        def __init__(self, *args):
            assert args[-1] == receiver
            graph = hs.Graph("camera_inner", default_clock=hs.RealtimeClock)
            graph.op(Tick, "tick", hz=30)
            self.session = ApplicationSession(graph)
            self.session.__enter__()

        def read(self):
            return None

        def close(self):
            # SDK 5 rejects this join when called directly by the outer callback.
            self.session.__exit__(None, None, None)
            stopped.append(True)

    fake = SimpleNamespace(Capture=NativeCapture)
    import telesurgery_runtime.backends.sdk5 as native

    monkeypatch.setitem(sys.modules, "telesurgery_runtime.backends.sdk5._hsb", fake)
    monkeypatch.setattr(native, "_hsb", fake, raising=False)

    class CameraOp(Tick):
        def start(self):
            self.camera = Imx274Camera(Config(receiver=receiver))

        def compute(self, context):
            assert self.camera.read() is None

        def stop(self):
            self.camera.close()

    graph = hs.Graph("camera_outer", default_clock=hs.RealtimeClock)
    graph.op(CameraOp, "camera", hz=30)
    with ApplicationSession(graph) as session:
        time.sleep(0.2)
        assert session.is_running()
    assert stopped == [True]
