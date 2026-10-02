# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""HSB IMX274: native SDK 5 acquisition, owned GPU frames, GPU demosaic."""

from concurrent.futures import ThreadPoolExecutor

from telesurgery_core.adapters.base import CameraSample
from telesurgery_core.video.gpu import demosaic


class Imx274Camera:
    def __init__(self, config):
        try:
            import cupy as cp
            from telesurgery_runtime.sdk5 import _hsb
        except ImportError as exc:
            raise RuntimeError("Build the SDK 5 HSB binding; see README.md") from exc
        self.cp = cp
        self.device = cp.cuda.Device(config.codec_gpu)
        with self.device:
            self.stream = cp.cuda.Stream(non_blocking=True)
        # SDK 5 forbids joining any RunSession from a runtime callback. Own the
        # nested native graph's start/stop on an ordinary Python worker instead.
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hsb-lifecycle")
        try:
            self.capture = self.worker.submit(
                _hsb.Capture,
                config.hololink,
                0 if config.width == 3840 else 1,
                config.expander,
                config.codec_gpu,
                not config.skip_reset,
            ).result()
        except BaseException:
            self.worker.shutdown(wait=True)
            raise
        self.pattern = self.capture.bayer_format

    def read(self):
        frame = self.capture.read()
        if frame is None:
            return None
        with self.device, self.stream:
            # The native boundary makes one owned GPU copy while its SDK lease is live.
            # Array import below is a view, not another transfer.
            bayer = self.cp.asarray(frame.tensor)
            image = demosaic(self.cp, bayer, self.pattern)
            self.stream.synchronize()
        return CameraSample(
            image,
            frame.host_received_ns,
            started_ns=frame.buffer_ready_ns,
        )

    def close(self):
        try:
            self.worker.submit(self.capture.close).result()
        finally:
            self.worker.shutdown(wait=True)


def discover():
    from telesurgery_runtime.sdk5 import _hsb

    return _hsb.discover()
