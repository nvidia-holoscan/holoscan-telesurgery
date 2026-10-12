# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cache one real GPU codec check per node process, outside frame processing."""

import importlib.util
import logging
from functools import lru_cache

from telesurgery_core.video.codecs import probe
from telesurgery_core.video.config import Config


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
