# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One independently supervised camera graph; exports encoded frames over local IPC."""

import argparse
import contextlib
import json
import os
import signal
import threading
import time
from pathlib import Path

from telesurgery_core.adapters.cameras import open_camera
from telesurgery_core.transport.protocol import MAX_RAW_VIDEO, VideoHeader
from telesurgery_core.video.codecs import CodecWorker
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame
from telesurgery_runtime.sdk import ApplicationSession, backend, require_sdk


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
        return Frame(header, sample.image, ready_ns=ready)

    def stop(self):
        if self.camera is not None:
            self.camera.close()


class Encode:
    def __init__(self, config):
        self.config = config
        self.codec = None

    def start(self):
        self.codec = CodecWorker(self.config, encode=True)

    def compute(self, frame):
        return self.codec.encode(frame)

    def stop(self):
        if self.codec is not None:
            self.codec.close()


class Publish:
    def __init__(self, endpoint):
        self.endpoint, self.socket = endpoint, None

    def start(self):
        import zmq
        from telesurgery_core.transport.zmq import open_socket

        self.socket = open_socket(zmq.PUB, self.endpoint, bind=True, max_size=MAX_RAW_VIDEO)

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
    stages = [Capture(config, camera), Encode(config), Publish(settings["endpoint"])]
    graph = backend("pipeline").build(
        "camera", stages, config.fps if config.source == "synthetic" else 1000
    )
    with ApplicationSession(graph) as session:
        while not stop.wait(0.02) and session.is_running():
            if settings.get("parent") and os.getppid() != settings["parent"]:
                break


if __name__ == "__main__":
    main()
