# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cache one real GPU codec check per node process, outside frame processing."""

import importlib.util
import logging
import time
from functools import lru_cache

import numpy as np
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video.codecs import create_codec, probe
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame
from telesurgery_core.video.region import VIDEO_CODECS


@lru_cache(maxsize=1)
def supported_codecs():
    available = []
    for codec in ("h264", "h265", "nvjpeg"):
        try:
            probe(Config(codec=codec))
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            logging.getLogger(__name__).warning("%s unavailable on this node: %s", codec, exc)
        else:
            available.append(codec)
    # First selection prepares the pinned model; discovery must not download models
    # or build engines while the operator is waiting for the device inventory.
    if available and any(
        importlib.util.find_spec(module) is not None for module in ("tensorrt", "tensorrt_bindings")
    ):
        available.append("surgical-tokenizer")
    return [*available, "raw-bgr8"]


@lru_cache(maxsize=1)
def region_supported():
    """True when this node's H.264/H.265 encoder can take a priority area.

    The encoder reports it after its first frame, so encode one small frame.
    """
    width, height = 320, 240
    for codec in VIDEO_CODECS:
        try:
            encoder = create_codec(Config(codec=codec, width=width, height=height), encode=True)
        except (ImportError, OSError, RuntimeError, ValueError):
            continue
        try:
            pixels = np.zeros((height, width, 3), dtype=np.uint8)
            encoder.encode(Frame(VideoHeader(0, time.time_ns(), width, height), pixels))
            return bool(getattr(encoder, "supports_region", False))
        except (OSError, RuntimeError, ValueError):
            continue
        finally:
            encoder.close()
    return False
