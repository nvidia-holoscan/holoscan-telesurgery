# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native GPU display graph for the default backend."""

import cupy as cp
import holoscan as hs
from holoscan.schema import Image
from holoscan.schema.image import ImageEncoding
from holoscan_visualization.operators import HolovizOp
from telesurgery_runtime.backends.sdk5.operators import PeriodicOp, connect
from telesurgery_runtime.backends.sdk5.session import ApplicationSession


def build(source, width, height, title):
    maximum_width = width * (2 if getattr(source, "depth_enabled", False) else 1)

    class ReceiveDecode(PeriodicOp):
        out = hs.Output("out", Image)

        def setup(self, spec):
            spec.output(self.out).produces_tensor(
                hs.tensor.OutputSpec(
                    storage="runtime_pool",
                    memory_kind=hs.tensor.MemoryKind.CUDA_DEVICE,
                    dtype=hs.tensor.DLDataType(1, 8, 1),
                    rank=3,
                ),
                hs.tensor.byte_span(maximum_width * height * 3),
                field="data",
            )

        def start(self):
            source.start()

        def compute(self, context):
            image = source.compute()
            if image is not None:
                descriptor = Image(
                    width=image.shape[1], height=image.shape[0], encoding=ImageEncoding.RGB8
                )
                request = hs.tensor.LoanRequest(
                    shape=image.shape, dtype=hs.tensor.DLDataType(1, 8, 1)
                )
                with self.out.allocate_tensors(descriptor, {"data": request}) as loan:
                    # Holoviz requires provider-owned storage with a CUDA lifetime contract.
                    with context.stream():
                        stream = cp.cuda.get_current_stream()
                        # The crop is a strided view of the decoder allocation.
                        # Reuse the existing provider handoff, copying only its
                        # rows; do not materialize a contiguous zoom image first.
                        cp.cuda.runtime.memcpy2DAsync(
                            loan.tensors["data"].data,
                            image.shape[1] * 3,
                            image.data.ptr,
                            image.strides[0],
                            image.shape[1] * 3,
                            image.shape[0],
                            cp.cuda.runtime.memcpyDeviceToDevice,
                            stream.ptr,
                        )
                        stream.synchronize()
                source.submitted()

        def stop(self):
            source.stop()

    graph = hs.Graph("telesurgery-holoviz", default_clock=hs.RealtimeClock)
    receive = graph.op(ReceiveDecode, "receive_decode", hz=1000)
    display = HolovizOp(
        graph,
        "display",
        layers=[
            {
                "kind": "image",
                "port_name": "video",
                "format": "rgb8_unorm",
                "max_width": maximum_width,
                "max_height": height,
            }
        ],
        sink={
            "kind": "window",
            "title": title,
            "width": min(width, 1280),
            "height": min(height, 720),
            "present_mode": "immediate",
        },
    )
    connect(graph, receive.out, display.video)
    graph.partition("decode").add(receive)
    graph.partition("display").add(display)
    options = hs.CompileOptions()
    options.deployment.bind_tensor_output_device(
        operator_path="receive_decode", output_port="out", device=hs.execution.DeviceId(0)
    )
    return ApplicationSession(graph, options)
