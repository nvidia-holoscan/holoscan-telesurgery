# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""GPU codecs for the Python Holoscan operators; no software codec fallback.

Each instance belongs to one operator. Calls may migrate between SDK workers,
so every call selects its CUDA device and enters its owned stream explicitly.
"""

from __future__ import annotations

import importlib.metadata
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
from telesurgery_core.transport.protocol import MAX_VIDEO, VideoHeader
from telesurgery_core.video import depth
from telesurgery_core.video.formats import dimensions
from telesurgery_core.video.gpu import nv12 as _nv12
from telesurgery_core.video.model import Frame


class _CudaBuffer:
    """PyNvVideoCodec 2.2.3 dispatches GPU input through a cuda() method."""

    def __init__(self, array):
        self.array = array

    def cuda(self):
        # Explicit contiguous planes avoid 2.2.3's positional __dlpack__(stream)
        # call, which is incompatible with CuPy 14's keyword-only stream.
        height = self.array.shape[0] * 2 // 3
        return (
            self.array[:height, :, None],
            self.array[height:].reshape(height // 2, self.array.shape[1] // 2, 2),
        )


class CodecWorker:
    """Call NVIDIA's Python bindings on one Python-owned thread per operator.

    With these wheels, nested pybind11 GIL guards on SDK-created worker threads
    can delete the active CPython thread state. A Python-created thread owns its
    state independently. Calls are synchronous, so no extra frame queue develops.
    """

    def __init__(self, config, *, encode):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu-codec")
        try:
            self.codec = self.executor.submit(create_codec, config, encode=encode).result()
            if encode and config.codec != "raw-bgr8":
                self.executor.submit(self._warmup, config).result()
        except BaseException:
            self.executor.shutdown()
            raise

    def _warmup(self, config):
        # Compile CUDA kernels and initialize NVENC before admitting live camera frames.
        image = np.zeros((config.height, config.width, 3), dtype=np.uint8)
        header = VideoHeader(0, time.time_ns(), config.width, config.height)
        for _ in range(3):
            self.codec.encode(Frame(header, image))

    def encode(self, frame):
        return self.executor.submit(self._encode, frame).result()

    def _encode(self, frame):
        header, data = self.codec.encode(frame)
        if frame.depth is None:
            return header, data
        started = header.encoded_ns
        header, data = depth.attach(header, data, frame.depth)
        finished = time.perf_counter_ns()
        return replace(
            header, pack_ns=header.pack_ns + finished - started, encoded_ns=finished
        ), data

    def _decode(self, header, data, on_device=False):
        color, packed = depth.split(header, data)
        frame = self.codec.decode(header, color, on_device=on_device)
        frame.depth = depth.unpack(header, packed)
        return frame

    def decode(self, header, data):
        return self.executor.submit(self._decode, header, data).result()

    def decode_device(self, header, data):
        return self.executor.submit(self._decode, header, data, on_device=True).result()

    def close(self):
        try:
            self.executor.submit(self.codec.close).result()
        finally:
            self.executor.shutdown()


def create_codec(config, *, encode):
    if config.codec == "raw-bgr8":
        from telesurgery_core.video.raw import RawCodec

        return RawCodec(config, encode=encode)
    return GpuCodec(config, encode=encode)


def encoder_options(config, width, height):
    """Shared application/benchmark settings; no additional NVENC output queue."""
    return {
        "codec": "hevc" if config.codec == "h265" else "h264",
        "profile": "main" if config.codec == "h265" else "baseline",
        "preset": config.encoder_preset,
        "tuning_info": "ultra_low_latency",
        "fps": config.fps,
        "gop": 1,
        "idrperiod": 1,
        "bf": 0,
        "lookahead": 0,
        "repeatspspps": 1,
        "rc": "constqp",
        "constqp": config.qp,
        "max_res": [width, height],
        "extra_output_delay": 0,
    }


class GpuCodec:
    """Own either an encoder or decoder and its CUDA stream.

    H.264/H.265 use 8-bit 4:2:0 all-IDR access units with parameter sets. This deliberately
    permits latest-frame transports, late join, and loss without reference repair.
    The locally built NVIDIA binding exposes extra_output_delay; require zero.
    """

    def __init__(self, config, *, encode: bool):
        self.kind, self.encoding = config.codec, encode
        self.config = config
        self.backend = None
        self.dimensions = None
        self.closed = False
        try:
            import cupy as cp

            self.cp = cp
            self.device = cp.cuda.Device(config.codec_gpu)
            with self.device:
                self.stream = cp.cuda.Stream(non_blocking=True)
                with self.stream:
                    if self.kind in {"h264", "h265"}:
                        import PyNvVideoCodec as nvc

                        self.library = nvc
                        if encode and getattr(nvc, "telesurgery_low_latency_patch", None) != 1:
                            raise RuntimeError(
                                "NVENC requires the zero-output-delay NVIDIA binding: run "
                                "scripts/builders/codecs.py with this Python"
                            )
                        # Native camera dimensions may differ from the display size.
                        # Create NVENC/NVDEC on the first validated frame.
                    elif self.kind == "nvjpeg":
                        from telesurgery_core.video.jpeg import JpegCodec

                        self.backend = JpegCodec(config, encode=encode, stream=self.stream.ptr)
                    else:
                        raise ValueError(f"unsupported GPU codec: {self.kind}")
        except (ImportError, OSError) as exc:
            raise RuntimeError(
                "GPU codecs require the codecs-cu13 extra, an NVIDIA driver with video support"
            ) from exc

    def _create_video(self, width, height):
        nvc = self.library
        self.dimensions = (width, height)
        if width % 2 or height % 2 or width < 32 or height < 32:
            raise ValueError("Video requires even dimensions of at least 32x32")
        if self.encoding:
            caps = nvc.GetEncoderCaps(
                self.config.codec_gpu, "hevc" if self.kind == "h265" else "h264"
            )
            if not (
                caps["width_min"] <= width <= caps["width_max"]
                and caps["height_min"] <= height <= caps["height_max"]
            ):
                raise ValueError(
                    f"{self.kind} dimensions {width}x{height} exceed this GPU's NVENC limits"
                )
            self.backend = nvc.CreateEncoder(
                width,
                height,
                "NV12",
                False,
                gpu_id=self.config.codec_gpu,
                cudastream=self.stream.ptr,
                **encoder_options(self.config, width, height),
            )
        else:
            self.backend = nvc.CreateDecoder(
                gpuid=self.config.codec_gpu,
                cudastream=self.stream.ptr,
                codec=nvc.cudaVideoCodec.HEVC if self.kind == "h265" else nvc.cudaVideoCodec.H264,
                usedevicememory=True,
                maxwidth=width,
                maxheight=height,
                outputColorType=nvc.OutputColorType.RGB,
                latency=nvc.DisplayDecodeLatencyType.LOW,
            )

    def encode(self, frame: Frame) -> tuple[VideoHeader, bytes]:
        started = time.perf_counter_ns()
        header = frame.header
        with self.device, self.stream:
            image = self.cp.asarray(frame.image)
            if image.dtype != self.cp.uint8 or image.shape != (header.height, header.width, 3):
                raise ValueError("encoder expects BGR8 matching the video header")
            if self.kind == "nvjpeg":
                data = self.backend.encode(image)
            else:
                if self.backend is None:
                    self._create_video(header.width, header.height)
                if self.dimensions != (header.width, header.height):
                    raise ValueError("restart the stream to change resolution")
                pixels = _nv12(self.cp, image)
                # The input remains live until NVENC's asynchronous copy completes.
                output = self.backend.Encode(_CudaBuffer(pixels))
                if len(output) != 1:
                    raise RuntimeError("NVENC must return one access unit immediately per input")
                data = output[0]["data"]
                if dimensions(self.kind, data) != (header.width, header.height):
                    raise RuntimeError("NVENC did not produce the required independent video frame")
            self.stream.synchronize()
        if not 0 < len(data) <= MAX_VIDEO:
            raise ValueError("encoded video exceeded the frame size limit")
        finished = time.perf_counter_ns()
        return replace(
            header,
            codec=self.kind,
            encode_ns=finished - started,
            encoder_queue_ns=started - frame.ready_ns if frame.ready_ns else 0,
            encoded_ns=finished,
        ), data

    def decode(self, header: VideoHeader, data: bytes, *, on_device=False) -> Frame:
        """Return owned RGB device pixels for display, or BGR host pixels for diagnostics."""
        if header.codec != self.kind:
            raise RuntimeError(
                f"codec mismatch: patient uses {header.codec}, surgeon expects {self.kind}"
            )
        size = dimensions(self.kind, data)
        if len(data) > MAX_VIDEO or size != (header.width, header.height):
            raise ValueError("compressed video dimensions do not match the bounded header")
        with self.device, self.stream:
            if self.kind == "nvjpeg":
                image = self.cp.asarray(self.backend.decode(data))
            else:
                if self.backend is None or self.dimensions != size:
                    self.backend = None
                    self._create_video(*size)
                array = np.frombuffer(data, dtype=np.uint8)
                packet = self.library.PacketData()
                packet.bsl, packet.bsl_data = array.size, array.ctypes.data
                packet.decode_flag = self.library.VideoPacketFlag.ENDOFPICTURE
                frames = self.backend.Decode(packet)
                if len(frames) != 1:
                    self.backend = None
                    raise ValueError("NVDEC did not return exactly one independent frame")
                image = self.cp.from_dlpack(frames[0])
            if image.shape != (header.height, header.width, 3):
                raise ValueError("decoded video dimensions do not match the header")
            if on_device:
                # NVDEC recycles its surfaces. Own a device copy until Holoviz has
                # consumed it; no uncompressed pixels cross to host memory.
                owned = image.copy()
                self.stream.synchronize()
                return Frame(header, owned)
            image = image[..., ::-1]
            # Diagnostic decoding returns owned BGR pixels; streaming forwards encoded packets.
            import cupyx

            # Pageable fresh NumPy allocations caused 30-70 ms transfers on Thor at 4K.
            # The pinned pool reuses released buffers; each Frame still owns its array.
            host = cupyx.empty_pinned(image.shape, dtype=image.dtype)
            image.get(out=host, stream=self.stream, blocking=False)
            self.stream.synchronize()
        return Frame(
            header,
            host,
        )

    def close(self):
        if self.closed:
            return
        self.closed = True
        with self.device, self.stream:
            if self.encoding and self.kind in {"h264", "h265"} and self.backend is not None:
                # No frames remain buffered with zero delay and no B frames/lookahead.
                self.backend.EndEncode()
            self.stream.synchronize()
            if self.kind == "nvjpeg" and self.backend is not None:
                self.backend.close()
            self.backend = None


def describe(config, *, encoding=True):
    if config.codec == "raw-bgr8":
        return {"name": config.codec, "compression": False, "bytes_per_pixel": 3}
    package = "nvidia-nvimgcodec-cu13" if config.codec == "nvjpeg" else "pynvvideocodec"
    return {
        "name": config.codec,
        "library": package,
        "version": importlib.metadata.version(package),
        "gpu": config.codec_gpu,
        "cpu_codec_fallback": False,
        "independent_frames": True,
        "encoder_settings": (
            {
                key: value
                for key, value in encoder_options(config, config.width, config.height).items()
                if key != "max_res"  # Allocation limits come from the actual input frame.
            }
            if config.codec != "nvjpeg"
            else {"jpeg_quality": config.jpeg_quality}
        )
        if encoding
        else "see patient report",
        "encode_timing": "input to encoded bytes, including internal buffering and transfers",
    }


def probe(config):
    """Exercise the selected stream format, including immediate output, for doctor."""
    from contextlib import ExitStack

    with ExitStack() as stack:
        encoder = create_codec(config, encode=True)
        stack.callback(encoder.close)
        decoder = create_codec(config, encode=False)
        stack.callback(decoder.close)
        pixels = np.full((240, 320, 3), (40, 90, 180), dtype=np.uint8)
        header = VideoHeader(0, time.time_ns(), 320, 240)
        frame = decoder.decode(*encoder.encode(Frame(header, pixels)))
        if np.abs(frame.image.astype(float) - pixels).mean() > 10:
            raise RuntimeError("GPU codec probe produced unexpected colors")
        return {
            **describe(config),
            "round_trip": "passed",
            "probe_dimensions": [320, 240],
            "first_frame_immediate": True,
        }
