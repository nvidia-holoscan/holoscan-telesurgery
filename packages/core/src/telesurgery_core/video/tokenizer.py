# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Public Cosmos-Tokenizer-Surg ONNX models executed on an owned CUDA stream."""

import fcntl
import hashlib
import json
import logging
import threading
import time
from dataclasses import replace

import numpy as np
from telesurgery_core.video.model import Frame
from telesurgery_core.video.tokenizer_model import (
    CODEC,
    HASHES,
    PROFILE,
    artifact,
    payload_size,
    token_shape,
)

_LOGGER = None
_LOGGER_LOCK = threading.Lock()


def runtime():
    """Use JetPack bindings on Thor or the CUDA wheel bindings on discrete GPUs."""
    try:
        import tensorrt as trt
    except ModuleNotFoundError as exc:
        if exc.name != "tensorrt":
            raise
        import tensorrt_bindings as trt
    return trt


def logger():
    trt = runtime()

    global _LOGGER
    with _LOGGER_LOCK:
        if _LOGGER is None:
            _LOGGER = trt.Logger(trt.Logger.WARNING)
        return _LOGGER


def unpack_tokens(data, width, height):
    if len(data) != payload_size(width, height):
        raise ValueError("Incorrect surgical tokenizer payload length")
    tokens = np.frombuffer(data, dtype="<u2")
    if tokens.max() >= 64000:
        raise ValueError("Invalid surgical tokenizer index")
    return tokens.astype(np.int32).reshape(token_shape(width, height))


class Engine:
    def __init__(self, cp, trt, stream, width, height, part):
        self.cp, self.stream = cp, stream
        self.logger = logger()
        model = artifact(height, part)
        device = cp.cuda.runtime.getDeviceProperties(cp.cuda.Device().id)
        # Thor's dynamic kernel generation can take many minutes per graph.
        # Precompiled tactics keep first selection practical on its JetPack runtime.
        optimization = 0 if (device["major"], device["minor"]) == (11, 0) else 3
        identity = {
            "model": HASHES[height, part],
            "trt": trt.__version__,
            "cuda": cp.cuda.runtime.runtimeGetVersion(),
            "gpu": str(device["name"]),
            "compute": [device["major"], device["minor"]],
            "precision": "fp32" if part == "quantizer" else "fp16",
            "builder": 2 if optimization == 0 else 1,
        }
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
        path = model.with_suffix(f".{key}.engine")
        self.runtime = trt.Runtime(self.logger)
        with path.with_suffix(".lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.engine = (
                self.runtime.deserialize_cuda_engine(path.read_bytes()) if path.exists() else None
            )
            if self.engine is None:
                logging.getLogger(__name__).info("Building surgical tokenizer engine: %s", part)
                builder = trt.Builder(self.logger)
                network = builder.create_network(0)
                parser = trt.OnnxParser(network, self.logger)
                if not parser.parse(model.read_bytes()):
                    raise RuntimeError(str([parser.get_error(i) for i in range(parser.num_errors)]))
                config = builder.create_builder_config()
                config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 30)
                config.clear_flag(trt.BuilderFlag.TF32)
                if part != "quantizer":
                    config.set_flag(trt.BuilderFlag.FP16)
                config.builder_optimization_level = optimization
                plan = builder.build_serialized_network(network, config)
                if plan is None:
                    raise RuntimeError(f"Failed to build surgical tokenizer {part}")
                temporary = path.with_suffix(".building")
                temporary.write_bytes(bytes(plan))
                temporary.replace(path)
                self.engine = self.runtime.deserialize_cuda_engine(plan)
        if self.engine is None:
            raise RuntimeError(f"Failed to load surgical tokenizer {part}")
        self.context = self.engine.create_execution_context()
        self.input = self.engine.get_tensor_name(0)
        self.output = self.engine.get_tensor_name(1)
        self.input_shape = tuple(self.engine.get_tensor_shape(self.input))
        output_shape = tuple(self.context.get_tensor_shape(self.output))
        expected = {
            "encoder": ((1, 3, height, width), (1, 16, height // 8, width // 8)),
            "quantizer": ((1, 16, height // 8, width // 8), token_shape(width, height)),
            "decoder": (token_shape(width, height), (1, 3, height, width)),
        }
        if (self.input_shape, output_shape) != expected[part]:
            raise RuntimeError(f"Unexpected surgical tokenizer {part} tensor shapes")
        self.dtype = np.dtype(trt.nptype(self.engine.get_tensor_dtype(self.input)))
        self.buffer = cp.empty(
            output_shape, dtype=trt.nptype(self.engine.get_tensor_dtype(self.output))
        )
        self.context.set_tensor_address(self.output, self.buffer.data.ptr)

    def run(self, value):
        if (
            value.shape != self.input_shape
            or value.dtype != self.dtype
            or not value.flags.c_contiguous
        ):
            raise ValueError("Unexpected surgical tokenizer input tensor")
        self.context.set_tensor_address(self.input, value.data.ptr)
        if not self.context.execute_async_v3(stream_handle=self.stream.ptr):
            raise RuntimeError("Surgical tokenizer inference failed")
        return self.buffer

    def close(self):
        self.context = self.buffer = None
        self.engine = None
        self.runtime = None


class TokenizerCodec:
    def __init__(self, config, *, encode):
        import cupy as cp

        trt = runtime()
        token_shape(config.width, config.height)
        self.cp, self.config, self.encoding = cp, config, encode
        self.closed = False
        self.device = cp.cuda.Device(config.codec_gpu)
        with self.device:
            self.stream = cp.cuda.Stream(non_blocking=True)
            with self.stream:
                self.engines = {
                    part: Engine(cp, trt, self.stream, config.width, config.height, part)
                    for part in (("encoder", "quantizer") if encode else ("decoder",))
                }

    def encode(self, frame):
        started = time.perf_counter_ns()
        header, cp = frame.header, self.cp
        if (header.width, header.height) != (self.config.width, self.config.height):
            raise ValueError("Surgical tokenizer resolution changed")
        with self.device, self.stream:
            image = cp.asarray(frame.image)
            if image.dtype != cp.uint8 or image.shape != (header.height, header.width, 3):
                raise ValueError("encoder expects BGR8 matching the video header")
            rgb = cp.ascontiguousarray(image[..., ::-1].transpose(2, 0, 1)[None], dtype=cp.float32)
            rgb *= 2 / 255
            rgb -= 1
            latent = self.engines["encoder"].run(rgb)
            indices = self.engines["quantizer"].run(latent)
            if bool(cp.any((indices < 0) | (indices >= 64000))):
                raise ValueError("Surgical tokenizer produced invalid indices")
            data = cp.asnumpy(indices.astype(cp.uint16)).astype("<u2", copy=False).tobytes()
            self.stream.synchronize()
        finished = time.perf_counter_ns()
        return replace(
            header,
            codec=CODEC,
            codec_profile=PROFILE,
            encode_ns=finished - started,
            encoder_queue_ns=started - frame.ready_ns if frame.ready_ns else 0,
            encoded_ns=finished,
        ), data

    def decode(self, header, data, *, on_device=False):
        if header.codec != CODEC or header.codec_profile != PROFILE:
            raise ValueError("Unknown surgical tokenizer model profile")
        if (header.width, header.height) != (self.config.width, self.config.height):
            raise ValueError("Surgical tokenizer resolution changed")
        tokens = unpack_tokens(data, header.width, header.height)
        cp = self.cp
        with self.device, self.stream:
            indices = cp.asarray(tokens)
            output = self.engines["decoder"].run(indices)
            rgb = cp.ascontiguousarray(
                cp.clip((output[0].transpose(1, 2, 0) + 1) * 127.5, 0, 255).astype(cp.uint8)
            )
            image = rgb if on_device else cp.asnumpy(rgb[..., ::-1])
            self.stream.synchronize()
        return Frame(header, image)

    def close(self):
        if not self.closed:
            self.closed = True
            with self.device:
                self.stream.synchronize()
                for engine in self.engines.values():
                    engine.close()
                self.engines.clear()
