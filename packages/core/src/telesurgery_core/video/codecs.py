# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""GPU codecs for the Python Holoscan operators; no software codec fallback.

Each instance belongs to one operator. Calls may migrate between SDK workers,
so every call selects its CUDA device and enters its owned stream explicitly.
"""

from __future__ import annotations

import importlib.metadata
import logging
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
from telesurgery_core.transport.protocol import MAX_VIDEO, VideoHeader
from telesurgery_core.video import depth
from telesurgery_core.video.encoder_settings import (
    automatic_bitrate,
    bitrate,
    parse_extra,
    validate,
)
from telesurgery_core.video.formats import video_frame
from telesurgery_core.video.gpu import nv12 as _nv12
from telesurgery_core.video.model import Frame
from telesurgery_core.video.reference import MissingReference, ReferenceChain

# H.264/H.265 run IPPP with a long GOP. Loss or a new viewer forces an IDR, so the
# periodic one is only a backstop and the GOP stays long.
GOP_SECONDS = 10
# Priority area: NVIDIA's converter (native/cae) takes one policy per map cell: 0 Neutral,
# 1 Protect and 2 ProtectStrong quantize more finely (-4 and -8 QP), 3 Deprioritize and
# 4 DeprioritizeStrong more coarsely (+4 and +8).
# "strong" (default) is meant to be seen. The area is encoded 16 QP finer than the rest of
# the picture, and the encoder is given less to spend: the rest, now coarser, keeps
# AREA_REST_RATE of its share of the bitrate limit. The area holds or gains quality, the
# rest is visibly softer, and bandwidth falls to between a quarter and a half.
# A stream already near starvation is not cut further (AREA_FLOOR of the automatic bitrate
# for its size): there the same 16 QP move quality into the area at the bandwidth it has.
# "subtle" moves quality at the same bandwidth: rate control holds the bitrate, so a small
# area gains 2 to 3 dB for under 0.5 dB outside.
# Constant QP has no rate control to rebalance. "subtle" leaves the rest at the chosen QP
# and the area costs bandwidth; "strong" also coarsens the rest by 8, which saves
# bandwidth for a small area and about breaks even at a quarter of the picture.
AREA_POLICY = {"strong": (2, 4), "subtle": (1, 3)}  # inside, outside
AREA_POLICY_CQP = {"strong": (1, 4), "subtle": (1, 0)}
AREA_REST_RATE = 0.2
AREA_FLOOR = 0.25


def area_plan(config, cells):
    """(inside policy, outside policy, share of the bitrate limit) for an area's cells."""
    strength = parse_extra(config.encoder_extra).get("area_strength", "strong")
    if config.rate_control == "cqp":
        return *AREA_POLICY_CQP[strength], 1.0
    if strength == "subtle":
        return *AREA_POLICY[strength], 1.0
    share = np.count_nonzero(cells) / cells.size
    return *AREA_POLICY[strength], share + (1 - share) * AREA_REST_RATE


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
                # Warmup left the encoder mid-GOP; live video must begin with an IDR.
                self.request_keyframe()
        except BaseException:
            self.executor.shutdown()
            raise

    def _warmup(self, config):
        # Compile CUDA kernels and initialize NVENC before admitting live camera frames.
        image = np.zeros((config.height, config.width, 3), dtype=np.uint8)
        header = VideoHeader(0, time.time_ns(), config.width, config.height)
        for _ in range(3):
            self.codec.encode(Frame(header, image))

    def request_keyframe(self):
        """Make the next encoded frame an IDR; intra-only codecs already satisfy this."""
        request = getattr(self.codec, "request_keyframe", None)
        if request is not None:
            request()

    @property
    def supports_region(self):
        """True when this encoder can concentrate quality in a priority area."""
        return bool(getattr(self.codec, "supports_region", False))

    def set_region(self, mask):
        """Apply a priority area (telesurgery_core.video.region.mask), or None to clear it."""
        apply = getattr(self.codec, "set_region", None)
        if apply is not None:
            self.executor.submit(apply, mask).result()
        elif mask is not None:
            raise RuntimeError("This encoder cannot use a priority area")

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

    def _decode(self, header, data, on_device=False, prepare=None):
        color, packed = depth.split(header, data)
        if prepare is None:
            frame = self.codec.decode(header, color, on_device=on_device)
        elif isinstance(self.codec, GpuCodec):
            frame = self.codec.decode(header, color, on_device=on_device, prepare=prepare)
        else:
            frame = self.codec.decode(header, color, on_device=on_device)
            import cupy as cp

            with cp.cuda.Device(frame.image.device.id):
                prepare(frame.image)
                cp.cuda.get_current_stream().synchronize()
        frame.depth = depth.unpack(header, packed)
        return frame

    def decode(self, header, data):
        return self.executor.submit(self._decode, header, data).result()

    def decode_device(self, header, data, prepare=None):
        """Decode to owned device pixels for display.

        prepare(image) may read or draw on those pixels before they leave the decoder.
        Its GPU work is finished when this returns, at no extra synchronization for
        H.264/H.265/nvJPEG, where it joins the decoder's own stream.
        """
        return self.executor.submit(
            self._decode, header, data, on_device=True, prepare=prepare
        ).result()

    def close(self):
        try:
            self.executor.submit(self.codec.close).result()
        finally:
            self.executor.shutdown()


def create_codec(config, *, encode):
    if config.codec == "surgical-tokenizer":
        from telesurgery_core.video.tokenizer import TokenizerCodec

        return TokenizerCodec(config, encode=encode)
    if config.codec == "raw-bgr8":
        from telesurgery_core.video.raw import RawCodec

        return RawCodec(config, encode=encode)
    return GpuCodec(config, encode=encode)


def encoder_options(config, width, height):
    """Shared application/benchmark settings; no additional NVENC output queue.

    "cbr" (default) holds every predicted frame near its share of the link (bitrate /
    fps), so transmit time and latency stay predictable; easy scenes use less. An IDR of
    detailed content, or a limit too low for the scene, can exceed that share. It is
    NVENC's VBR mode with the peak equal to the average and a one-frame buffer:
    NVENC's own CBR mode produces the same pictures, then pads H.264 frames to the
    full budget with filler data (over 40% of a simulation stream).
    "vbr" lets hard frames use up to twice the average. "cqp" holds quality constant
    and lets frame size, including each IDR, vary.
    NVENC reads "bitrate" suffixes as powers of 1024, so pass exact bits per second.
    """
    extra = parse_extra(config.encoder_extra)
    gop = max(2, round(config.fps * extra.get("gop_seconds", GOP_SECONDS)))
    options = {
        "codec": "hevc" if config.codec == "h265" else "h264",
        "profile": "main" if config.codec == "h265" else "baseline",
        "preset": config.encoder_preset,
        "tuning_info": "ultra_low_latency",
        "fps": config.fps,
        "gop": gop,
        "idrperiod": gop,
        "bf": 0,
        "lookahead": 0,
        "repeatspspps": 1,
        "max_res": [width, height],
        "extra_output_delay": 0,
    }
    validate(config.rate_control, config.bitrate_mbps, config.qp)
    if config.rate_control == "cqp":
        options.update(rc="constqp", constqp=str(config.qp))
    else:
        bits = round(bitrate(config, width, height) * 1_000_000)
        peak = bits * 2 if config.rate_control == "vbr" else bits
        vbv = max(1, round(peak / config.fps * extra.get("vbv_frames", 1)))
        options.update(rc="vbr", bitrate=bits, maxbitrate=peak, vbvbufsize=vbv, vbvinit=vbv)
    for key in ("aq", "multipass", "qmax"):
        if key in extra:
            options[key] = str(extra[key])
    if extra.get("temporalaq"):  # the binding enables it for any value
        options["temporalaq"] = "1"
    return options


class GpuCodec:
    """Own either an encoder or decoder and its CUDA stream.

    H.264/H.265 use 8-bit 4:2:0 IPPP: an IDR with parameter sets, then predicted frames.
    Each frame's header carries its GOP position, so receivers detect loss on any
    latest-frame hop and ask the encoder for a new IDR (request_keyframe).
    The locally built NVIDIA binding exposes extra_output_delay; require zero.
    """

    def __init__(self, config, *, encode: bool):
        self.kind, self.encoding = config.codec, encode
        self.config = config
        self.backend = None
        self.dimensions = None
        self.closed = False
        self.keyframe_requested = True
        self.gop, self.gop_index = secrets.randbelow(2**30), 0
        self.chain = ReferenceChain()
        self.region = None  # policy map of the active priority area
        self.region_rate = 1.0  # share of the bitrate limit that area asks for
        self.rate = 1.0  # share the live encoder is using
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

    def request_keyframe(self):
        self.keyframe_requested = True

    # True once an H.264/H.265 encoder exists that accepts a priority area. The encoder is
    # created on the first frame, so read it after that.
    supports_region = False

    def set_region(self, mask):
        """Concentrate quality where mask (uint8 cells, 1 inside) is set; None restores uniform.

        The area takes effect on the next frame without an IDR. Before the first frame
        there is no encoder yet: the area is kept and applied when one is created.
        """
        video = self.encoding and self.kind in {"h264", "h265"}
        if mask is None:
            policy, rate = None, 1.0
        elif not video or (self.backend is not None and not self.supports_region):
            raise RuntimeError("This encoder cannot use a priority area")
        else:
            cells = np.asarray(mask)
            if cells.ndim != 2 or not cells.size:
                raise ValueError("A priority area mask is a two-dimensional grid")
            inside, outside, rate = area_plan(self.config, cells)
            policy = np.where(cells != 0, inside, outside).astype(np.uint8)
        if self.supports_region and self.backend is not None:
            with self.device, self.stream:
                self.backend.SetPolicyMap(policy)
                if not self._set_rate(self.backend, rate):
                    # The encoder kept a cut meant for an area that is gone or has grown,
                    # which would starve the whole picture. The next frame starts a new
                    # encoder at the bitrate limit, with an IDR.
                    self.backend.EndEncode()
                    self.stream.synchronize()
                    self.backend = None
                    self.keyframe_requested = True
        self.region, self.region_rate = policy, rate

    def _set_rate(self, backend, rate):
        """Give the live encoder this share of its bitrate limit. NVENC needs no IDR for it.

        The rate buffer keeps its size, so no frame may be larger than the limit already
        allowed. Scaled with the bitrate, each IDR would be coded so coarsely that the whole
        picture, the area included, blurs for a third of a second.
        Returns False when NVENC refused and the encoder is left with less than it should have.
        """
        options = encoder_options(self.config, *self.dimensions)
        if "bitrate" not in options:
            return True
        floor = AREA_FLOOR * automatic_bitrate(*self.dimensions) * 1_000_000
        rate = min(1.0, max(rate, floor / options["bitrate"]))
        if rate == self.rate:
            return True
        try:
            params = backend.GetEncodeReconfigureParams()
            params.averageBitrate = round(options["bitrate"] * rate)
            params.maxBitRate = round(options["maxbitrate"] * rate)
            params.vbvBufferSize = params.vbvInitialDelay = options["vbvbufsize"]
            if not backend.Reconfigure(params):
                raise RuntimeError("NVENC refused the new bitrate")
        except Exception:
            logging.warning(
                "Could not change the encoder's bitrate for a priority area", exc_info=True
            )
            # A refused cut only loses the bandwidth saving; the area itself is applied.
            return rate < self.rate
        self.rate = rate
        return True

    def _create_encoder(self, width, height):
        nvc = self.library
        options = encoder_options(self.config, width, height)

        def create(**extra):
            return nvc.CreateEncoder(
                width,
                height,
                "NV12",
                False,
                gpu_id=self.config.codec_gpu,
                cudastream=self.stream.ptr,
                **options,
                **extra,
            )

        self.supports_region = False
        self.rate = 1.0
        # NVENC's delta-QP map excludes its own adaptive quantization. Arming the map costs
        # nothing: without an area the stream is byte-identical.
        if getattr(nvc, "telesurgery_policy_map_patch", None) == 1 and not (
            {"aq", "temporalaq"} & options.keys()
        ):
            try:
                backend = create(qp_policy_map=1)
                self.supports_region = bool(backend.SupportsPolicyMap())
            except Exception:
                logging.warning(
                    "NVENC refused priority areas for this stream; continuing without them",
                    exc_info=True,
                )
            else:
                if self.region is not None and self.supports_region:
                    backend.SetPolicyMap(self.region)
                    self._set_rate(backend, self.region_rate)
                return backend
        return create()

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
            self.backend = self._create_encoder(width, height)
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
                force, self.keyframe_requested = self.keyframe_requested, False
                # The input remains live until NVENC's asynchronous copy completes.
                if force:
                    output = self.backend.Encode(
                        _CudaBuffer(pixels), int(self.library.NV_ENC_PIC_FLAGS.FORCEIDR)
                    )
                else:
                    output = self.backend.Encode(_CudaBuffer(pixels))
                if len(output) != 1:
                    raise RuntimeError("NVENC must return one access unit immediately per input")
                data = output[0]["data"]
                size, keyframe = video_frame(self.kind, data)
                if keyframe:
                    if size != (header.width, header.height):
                        raise RuntimeError("NVENC produced an IDR with unexpected dimensions")
                    self.gop, self.gop_index = (self.gop + 1) % 2**31, 0
                elif force:
                    raise RuntimeError("NVENC ignored the forced IDR")
                else:
                    self.gop_index += 1
            self.stream.synchronize()
        if not 0 < len(data) <= MAX_VIDEO:
            raise ValueError("encoded video exceeded the frame size limit")
        finished = time.perf_counter_ns()
        framing = (
            {"keyframe": keyframe, "gop": self.gop, "gop_index": self.gop_index}
            if self.kind in {"h264", "h265"}
            else {}
        )
        return replace(
            header,
            codec=self.kind,
            encode_ns=finished - started,
            encoder_queue_ns=started - frame.ready_ns if frame.ready_ns else 0,
            encoded_ns=finished,
            **framing,
        ), data

    def _check_reference(self, header, keyframe, size):
        """Reject a delta frame whose predecessor was lost; wait for the next IDR."""
        if not self.chain.accept(header):
            raise MissingReference("waiting for a keyframe after a lost reference frame")
        if not keyframe and (self.backend is None or self.dimensions != size):
            self.chain.reset()
            raise MissingReference("delta frame does not match the active decoder")

    def decode(self, header: VideoHeader, data: bytes, *, on_device=False, prepare=None) -> Frame:
        """Return owned RGB device pixels for display, or BGR host pixels for diagnostics."""
        if header.codec != self.kind:
            raise RuntimeError(
                f"codec mismatch: patient uses {header.codec}, surgeon expects {self.kind}"
            )
        size, keyframe = video_frame(self.kind, data)
        if keyframe != header.keyframe:
            raise ValueError("compressed video does not match its keyframe flag")
        if len(data) > MAX_VIDEO or size not in (None, (header.width, header.height)):
            raise ValueError("compressed video dimensions do not match the bounded header")
        size = (header.width, header.height)
        if self.kind != "nvjpeg":
            self._check_reference(header, keyframe, size)
        try:
            return self._decode(header, data, size, on_device, prepare)
        except Exception:
            # The decoder may not hold this frame; later deltas must wait for an IDR.
            self.chain.reset()
            raise

    def _decode(self, header, data, size, on_device, prepare=None):
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
                    raise ValueError("NVDEC did not return exactly one frame per packet")
                image = self.cp.from_dlpack(frames[0])
            if image.shape != (header.height, header.width, 3):
                raise ValueError("decoded video dimensions do not match the header")
            if on_device:
                # NVDEC recycles its surfaces. Own a device copy until Holoviz has
                # consumed it; no uncompressed pixels cross to host memory.
                owned = image.copy()
                if prepare is not None:
                    # On this stream, so the wait below also covers the caller's work.
                    prepare(owned)
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
    if config.codec == "surgical-tokenizer":
        from telesurgery_core.video.tokenizer import runtime
        from telesurgery_core.video.tokenizer_model import PROFILE

        return {
            "name": config.codec,
            "library": "tensorrt-cu13",
            "version": runtime().__version__,
            "profile": PROFILE,
            "gpu": config.codec_gpu,
            "independent_frames": True,
            "trial": True,
        }
    if config.codec == "raw-bgr8":
        return {"name": config.codec, "compression": False, "bytes_per_pixel": 3}
    package = "nvidia-nvimgcodec-cu13" if config.codec == "nvjpeg" else "pynvvideocodec"
    return {
        "name": config.codec,
        "library": package,
        "version": importlib.metadata.version(package),
        "gpu": config.codec_gpu,
        "cpu_codec_fallback": False,
        "independent_frames": config.codec == "nvjpeg",
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
        width, height = (
            (config.width, config.height) if config.codec == "surgical-tokenizer" else (320, 240)
        )
        pixels = np.full((height, width, 3), (40, 90, 180), dtype=np.uint8)
        header = VideoHeader(0, time.time_ns(), width, height)
        frame = decoder.decode(*encoder.encode(Frame(header, pixels)))
        if np.abs(frame.image.astype(float) - pixels).mean() > 10:
            raise RuntimeError("GPU codec probe produced unexpected colors")
        return {
            **describe(config),
            "round_trip": "passed",
            "probe_dimensions": [width, height],
            "first_frame_immediate": True,
            # False means surgeons are not offered priority areas: rerun setup.sh.
            "priority_area": bool(getattr(encoder, "supports_region", False)),
        }
