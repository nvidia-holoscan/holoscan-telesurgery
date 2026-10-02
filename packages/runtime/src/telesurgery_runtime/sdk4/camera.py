# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""IMX274 operators composed into the patient graph."""

from __future__ import annotations

import contextlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.gpu import demosaic
from telesurgery_core.video.model import Frame


@dataclass
class CameraSession:
    camera: object = None
    metadata: object = None
    cuda_context: object = None


@contextlib.contextmanager
def open_camera(config):
    """Keep HSB control and its CUDA context alive until the graph has stopped."""
    try:
        import hololink_module as hsb
        from cuda.bindings import driver as cuda
        from hololink_module.sensors.imx274 import Imx274Cam, imx274_mode
    except ImportError as exc:
        raise RuntimeError(
            "HSB capture requires hololink_module and CUDA Python; see README.md"
        ) from exc

    def checked(result):
        if result[0] != cuda.CUresult.CUDA_SUCCESS:
            raise RuntimeError(f"CUDA initialization failed: {result[0]}")
        return result[1] if len(result) > 1 else None

    checked(cuda.cuInit(0))
    device = checked(cuda.cuDeviceGet(config.codec_gpu))
    cuda_context = checked(cuda.cuDevicePrimaryCtxRetain(device))
    # ExitStack still releases the CUDA context if link shutdown fails.
    with contextlib.ExitStack() as stack:
        stack.callback(cuda.cuDevicePrimaryCtxRelease, device)
        metadata = adapter().wait_for_channel(config.hololink, 10.0)
        Imx274Cam.use_expander_configuration(metadata, config.expander)
        link = hsb.HololinkInterfaceV1.get_service(metadata)
        stack.callback(link.stop)
        link.start()
        if not config.skip_reset:
            link.reset()
        camera = Imx274Cam(metadata)
        mode = imx274_mode.Imx274_Mode(0 if config.width == 3840 else 1)
        camera.configure(mode)
        camera.set_digital_gain_reg(4)
        yield CameraSession(camera, metadata, cuda_context)


def camera_frame_adapter(app, channel, pattern):
    """Keep camera tensors on CUDA while respecting producer streams and ownership."""
    import cupy as cp
    from holoscan.core import Operator
    from telesurgery_runtime.sdk4.operators import latest_output

    class TensorToFrameOp(Operator):
        def setup(self, spec):
            spec.input("in")
            latest_output(spec)

        def start(self):
            self.sequence = 0

        def compute(self, op_input, op_output, context):
            message = op_input.receive("in")
            started = time.monotonic_ns()
            if len(message) != 1:
                raise ValueError("expected exactly one Bayer camera tensor")
            # Copy into owned GPU storage before the GXF message releases its pool slot.
            # Synchronize this boundary because Frame is a Python message without an SDK stream.
            stream = cp.cuda.ExternalStream(op_input.receive_cuda_stream("in"))
            with stream:
                pixels = cp.asarray(next(iter(message.values())))
                bgr = demosaic(cp, pixels, pattern)
                stream.synchronize()
            received = self.metadata.get("received_s", 0) * 1_000_000_000 + self.metadata.get(
                "received_ns", 0
            )
            header = VideoHeader(
                self.sequence,
                received or time.time_ns(),
                bgr.shape[1],
                bgr.shape[0],
                source_started_ns=max(0, started),
            )
            channel.send(op_output, Frame(header, bgr))
            self.sequence += 1

    return TensorToFrameOp(app, name="camera_to_frame")


def add_camera(app, config, session, output):
    """Return an operator producing Frame objects from an in-process vendor chain."""
    from holoscan.resources import BlockMemoryPool
    from telesurgery_runtime.sdk4.operators import source_conditions

    sink = camera_frame_adapter(app, output, session.camera.bayer_format().value)

    def pool(name, bytes_per_pixel, blocks=4):
        return BlockMemoryPool(
            app,
            name=name,
            storage_type=1,
            block_size=config.width * config.height * bytes_per_pixel,
            num_blocks=blocks,
        )

    import hololink_module.operators as hsb_ops

    camera = session.camera
    unpack = hsb_ops.CsiToBayerOp(
        app,
        name="csi_to_bayer",
        allocator=pool("bayer_pool", 2),
        cuda_device_ordinal=config.codec_gpu,
    )
    camera.configure_converter(unpack)
    receiver = hsb_ops.LinuxReceiverOp(
        app,
        *source_conditions(app),
        name="hsb_receiver",
        frame_size=unpack.get_csi_length(),
        frame_context=session.cuda_context,
        enumeration_metadata=session.metadata,
        device_start=camera.start,
        device_stop=camera.stop,
    )
    process = hsb_ops.ImageProcessorOp(
        app,
        name="black_level",
        optical_black=50,
        bayer_format=camera.bayer_format().value,
        pixel_format=camera.pixel_format().value,
    )
    app.add_flow(receiver, unpack, {("output", "input")})
    app.add_flow(unpack, process, {("output", "input")})
    app.add_flow(process, sink, {("output", "in")})
    return sink


class Imx274Camera:
    """Expose the native SDK 4 sensor graph through the shared camera interface."""

    def __init__(self, config):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Lock

        self.config, self.frame = config, None
        self.lock = Lock()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hsb-lifecycle")
        try:
            self.worker.submit(self._start).result()
        except BaseException:
            self.worker.shutdown()
            raise

    def _start(self):
        from holoscan.core import Application, Operator
        from telesurgery_runtime.sdk4.channel import LatestChannel
        from telesurgery_runtime.sdk4.operators import configure_scheduler, latest_input
        from telesurgery_runtime.sdk4.session import ApplicationSession

        owner = self
        channel = LatestChannel()
        self.resources = contextlib.ExitStack()
        try:
            camera = self.resources.enter_context(open_camera(self.config))

            class Store(Operator):
                def setup(self, spec):
                    latest_input(spec)

                def compute(self, op_input, op_output, context):
                    frame = channel.receive(op_input)
                    if frame is not None:
                        with owner.lock:
                            owner.frame = frame

            class Sensor(Application):
                def compose(self):
                    source = add_camera(self, owner.config, camera, channel)
                    self.add_flow(source, Store(self, name="latest_frame"), {("out", "in")})

            app = Sensor(argv=["hsb-camera"])
            configure_scheduler(app)
            self.resources.enter_context(ApplicationSession(app))
            # Stop incoming async events before waiting for the graph to drain.
            self.resources.callback(camera.camera.stop)
        except BaseException:
            self.resources.close()
            raise

    def read(self):
        from telesurgery_core.adapters.base import CameraSample

        with self.lock:
            frame, self.frame = self.frame, None
        return (
            None
            if frame is None
            else CameraSample(
                frame.image,
                frame.header.captured_ns,
                started_ns=frame.header.source_started_ns or -1,
            )
        )

    def close(self):
        try:
            self.worker.submit(self.resources.close).result()
        finally:
            self.worker.shutdown()


def adapter():
    import hololink_module as hsb

    instance = hsb.Adapter.get_adapter()
    path = Path(sys.prefix, "hsb-modules")
    if path.exists():
        instance.set_module_directory(path.read_text().strip())
    return instance


def discover():
    from threading import Lock

    instance, addresses, lock = adapter(), set(), Lock()

    def announced(metadata):
        with lock:
            addresses.add(metadata["peer_ip"])

    registration = instance.register_all(announced)
    try:
        time.sleep(0.5)
        with lock:
            return sorted(addresses)
    finally:
        instance.unregister(registration)
