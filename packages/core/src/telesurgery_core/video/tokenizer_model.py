# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Pinned public surgical tokenizer artifacts and fixed wire profile."""

import fcntl
import hashlib
import logging
import os
import urllib.request
from pathlib import Path

CODEC = "surgical-tokenizer"
REVISION = "97757e20556e8905dd3ddb0734d7c987bf4cc9e8"
PROFILE = f"cosmos-surg-{REVISION}-u16le"
RESOLUTIONS = ((1280, 720), (1920, 1080))
HASHES = {
    (720, "encoder"): "1f083d0b791983d4cb5fc918cff6d49bc01433cb15174ff8c811adaef574377a",
    (720, "quantizer"): "96126464259e93be1cf0c6d034ca73a1057b4563dc9f57cc3fa177a2573597d0",
    (720, "decoder"): "a80c5899556f517fbe4203d5000c17ec7ee9be9609a5430a588da1919cc9b17b",
    (1080, "encoder"): "9811f1df9b8aed0fcff820e833b2a70cec95b89db99a1e0c578d79d5a2fc6af9",
    (1080, "quantizer"): "a8c5fef2505d1854984c1560e6485b06e083328ab9b159a0ac245ccca8dbfbf7",
    (1080, "decoder"): "30db9e31f490cc9a7487f9f50b076eb6c75a03ee4cebbd76f0c131df577e9764",
}


def token_shape(width, height):
    if (width, height) not in RESOLUTIONS:
        raise ValueError("Surgical Neural Tokenizer supports 1280x720 and 1920x1080")
    return (1, height // 8, width // 8, 2)


def payload_size(width, height):
    token_shape(width, height)
    return width * height // 16


def cache_directory():
    workspace = Path(os.environ.get("TELESURGERY_WORKSPACE", "workspace"))
    return workspace / "cache" / "surgical-tokenizer" / REVISION


def artifact(height, part):
    """Fetch a fixed HTTPS artifact once, with a checksum and cross-process lock."""
    checksum = HASHES[height, part]
    name = f"{height}p/{part}_{height}p_cs_discrete8_wan_patch2.onnx"
    path = cache_directory() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
            return path
        url = f"https://huggingface.co/nvidia/Cosmos-Tokenizer-Surg/resolve/{REVISION}/{name}"
        logging.getLogger(__name__).info("Downloading surgical tokenizer %s", name)
        temporary = path.with_suffix(".download")
        try:
            # Fixed public HTTPS URL; verify the pinned artifact before using it.
            with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310
                content = response.read(32 * 1024 * 1024 + 1)
            if hashlib.sha256(content).hexdigest() != checksum:
                raise RuntimeError(f"Surgical tokenizer checksum mismatch: {name}")
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path
