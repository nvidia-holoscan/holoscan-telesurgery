# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One independently supervised camera graph; exports encoded frames over local IPC."""

import argparse
import contextlib
import json
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from telesurgery_core.adapters.cameras import open_camera
from telesurgery_core.transport.protocol import MAX_FRAME, VideoHeader
from telesurgery_core.video.codecs import CodecWorker
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame
from telesurgery_runtime.backends.sdk import ApplicationSession, backend, require_sdk


class Capture:
    def __init__(self, config, camera=None):
        self.config, self.camera, self.sequence = config, camera, 0

    def start(self):
        if self.camera is None:
            if self.config.source == "imx274":
                self.camera = backend("camera").Imx274Camera(self.config)
            else:
                self.camera = open_camera(self.config)

    def compute(self):
        sample = self.camera.read()
        ready = time.perf_counter_ns()
        if sample is None:
            return None
        source_started = sample.started_ns or ready
        header = VideoHeader(
            self.sequence,
            sample.captured_ns,
            sample.image.shape[1],
            sample.image.shape[0],
            sim_command_sequence=sample.sim_command_sequence,
            acquisition_ns=ready - source_started if source_started > 0 else 0,
            source_started_ns=max(0, source_started),
        )
        self.sequence += 1
        return Frame(header, sample.image, ready_ns=ready, depth=sample.depth)

    def stop(self):
        if self.camera is not None:
            self.camera.close()


class Encode:
    def __init__(self, config, settings_path=None):
        self.config = config
        self.codec = None
        self.settings_path = settings_path
        self.check_at, self.settings_stamp = 0, None
        self.preparing = self.builder = None
        self.requested = config
        self.failed = None

    def _error(self, message=""):
        if self.settings_path:
            path = self.settings_path.with_suffix(".error")
            if message:
                path.write_text(message)
            else:
                path.unlink(missing_ok=True)

    def start(self):
        self.codec = CodecWorker(self.config, encode=True)
        self.builder = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prepare-codec")

    def _refresh(self):
        if self.settings_path and time.monotonic() >= self.check_at:
            self.check_at = time.monotonic() + 0.25
            stamp = self.settings_path.stat().st_mtime_ns
            if stamp != self.settings_stamp:
                self.requested = Config(**json.loads(self.settings_path.read_text())["camera"])
                self.settings_stamp = stamp
                self.failed = None
                self._error()
        if self.preparing and self.preparing[1].done():
            config, future = self.preparing
            self.preparing = None
            try:
                replacement = future.result()
            except Exception as exc:
                if config == self.requested:
                    self.failed = config
                    self._error(
                        f"Could not prepare {config.codec}; continuing {self.config.codec}: {exc}"
                    )
                    logging.exception("Encoder change failed; retaining the active encoder")
                return
            if config == self.requested:
                old, self.codec, self.config = self.codec, replacement, config
                old.close()
            else:
                replacement.close()
        if self.preparing is None and self.requested not in (self.config, self.failed):
            self.preparing = (
                self.requested,
                self.builder.submit(CodecWorker, self.requested, encode=True),
            )

    def compute(self, frame):
        self._refresh()
        return self.codec.encode(frame)

    def stop(self):
        if self.builder is not None:
            self.builder.shutdown()
        if self.preparing is not None:
            future = self.preparing[1]
            if future.exception() is None:
                future.result().close()
        if self.codec is not None:
            self.codec.close()


class Publish:
    def __init__(self, endpoint):
        self.endpoint, self.socket = endpoint, None

    def start(self):
        import zmq
        from telesurgery_core.transport.zmq import open_socket

        self.socket = open_socket(zmq.PUB, self.endpoint, bind=True, max_size=MAX_FRAME)

    def compute(self, packet):
        import zmq

        header, data = packet
        with contextlib.suppress(zmq.Again):
            self.socket.send_multipart([header.encode(), data], flags=zmq.NOBLOCK)

    def stop(self):
        if self.socket is not None:
            self.socket.close(linger=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    settings = json.loads(args.config.read_text())
    config = Config(**settings["camera"])
    stop = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_: stop.set())
    require_sdk()
    # SDK 4 HSB capture owns a native sensor graph on an ordinary Python thread.
    camera = None
    if config.source == "imx274" and require_sdk().__version__.startswith("4."):
        camera = backend("camera").Imx274Camera(config)
    stages = [Capture(config, camera), Encode(config, args.config), Publish(settings["endpoint"])]
    graph = backend("pipeline").build(
        "camera", stages, config.fps if config.source == "synthetic" else 1000
    )
    with ApplicationSession(graph) as session:
        while not stop.wait(0.02) and session.is_running():
            if settings.get("parent") and os.getppid() != settings["parent"]:
                break


if __name__ == "__main__":
    main()
