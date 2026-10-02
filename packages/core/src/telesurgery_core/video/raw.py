# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Uncompressed BGR8 transport; measure copies without invoking a video codec."""

import time
from dataclasses import replace

from telesurgery_core.video.formats import decode_raw, encode_raw
from telesurgery_core.video.model import Frame


class RawCodec:
    def __init__(self, config, *, encode):
        self.gpu, self.stream = config.codec_gpu, None

    def _cuda(self):
        import cupy as cp

        device = cp.cuda.Device(self.gpu)
        with device:
            if self.stream is None:
                self.stream = cp.cuda.Stream(non_blocking=True)
        return cp, device, self.stream

    def encode(self, frame):
        started = time.perf_counter_ns()
        image = frame.image
        if hasattr(image, "__cuda_array_interface__"):
            cp, device, stream = self._cuda()
            with device, stream:
                image = cp.asnumpy(image, stream=stream)
        header, data = encode_raw(Frame(frame.header, image))
        finished = time.perf_counter_ns()
        return replace(
            header,
            encode_ns=0,
            pack_ns=finished - started,
            encoder_queue_ns=started - frame.ready_ns if frame.ready_ns else 0,
            encoded_ns=finished,
        ), data

    def decode(self, header, data, *, on_device=False):
        frame = decode_raw(header, data)
        if not on_device:
            return frame
        cp, device, stream = self._cuda()
        with device, stream:
            # Holoviz consumes owned RGB device pixels; the wire remains BGR8.
            pixels = cp.ascontiguousarray(cp.asarray(frame.image)[..., ::-1])
            stream.synchronize()
        return Frame(header, pixels)

    def close(self):
        self.stream = None
