# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the HSB runtime's nested graph lifecycle without a physical board."""

import contextlib
import threading
import time

import pytest

hs = pytest.importorskip("holoscan", exc_type=ImportError)
pytestmark = pytest.mark.sdk
if not hs.__version__.startswith("4."):
    pytest.skip("SDK 4 HSB lifecycle", allow_module_level=True)


def test_camera_session_starts_and_stops_on_its_owner_thread(monkeypatch):
    from telesurgery_core.video.config import Config
    from telesurgery_runtime.backends.sdk4.camera import Imx274Camera
    from telesurgery_runtime.backends.sdk4.pipeline import build
    from telesurgery_runtime.backends.sdk4.session import ApplicationSession

    events = []

    class Tick:
        def compute(self):
            return None

    def start(camera):
        events.append(("start", threading.get_ident()))
        camera.resources = contextlib.ExitStack()
        camera.resources.callback(lambda: events.append(("stop", threading.get_ident())))
        camera.resources.enter_context(ApplicationSession(build("sensor", [Tick()])))

    monkeypatch.setattr(Imx274Camera, "_start", start)

    class Capture(Tick):
        def start(self):
            self.camera = Imx274Camera(Config())

        def compute(self):
            assert self.camera.read() is None

        def stop(self):
            self.camera.close()

    for _ in range(2):
        with ApplicationSession(build("outer", [Capture()])) as session:
            time.sleep(0.1)
            assert session.is_running()
        assert events[-2][0] == "start" and events[-1][0] == "stop"
        assert events[-2][1] == events[-1][1] != threading.get_ident()
