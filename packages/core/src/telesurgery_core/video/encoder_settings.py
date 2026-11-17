# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Rate control and the curated advanced NVENC settings.

Advanced settings are ``key=value`` lines. Adding a key to ``OPTIONS`` makes it
available everywhere (stream dialog, API, benchmark) with no other code change.
Keys outside the table are rejected: the NVIDIA binding silently ignores
unknown keys and falls back to CBR for an unknown rate control, which would
make an experiment look as if it had run when it had not.
"""

from __future__ import annotations

import math

RATE_CONTROLS = ("cbr", "vbr", "cqp")
MIN_MBPS, MAX_MBPS = 0.5, 400
AUTOMATIC = 0  # bitrate_mbps value that selects automatic_bitrate() for the stream's size.
MIN_QP, MAX_QP = 10, 51
MAX_EXTRA = 512

# Keys the pipeline depends on; naming one gives a specific error.
PROTECTED = {
    "codec": "set by the stream codec",
    "profile": "fixed by the stream codec",
    "rc": "use the rate control setting",
    "bitrate": "use the bitrate setting",
    "maxbitrate": "derived from the bitrate setting",
    "constqp": "use the QP setting",
    "bf": "B-frames would reorder output; the stream is IPPP",
    "lookahead": "lookahead adds output delay",
    "extra_output_delay": "frames must leave the encoder immediately",
    "idrperiod": "use gop_seconds",
    "gop": "use gop_seconds",
    "max_res": "taken from the camera",
    "fps": "taken from the camera",
    "tuning_info": "fixed to ultra low latency",
    "preset": "use the encoder speed setting",
    "vbvbufsize": "use vbv_frames",
    "vbvinit": "use vbv_frames",
    "repeatspspps": "receivers need parameter sets on every IDR",
}


def _integer(low, high):
    def parse(value):
        number = float(value)
        if not number.is_integer() or not low <= number <= high:
            raise ValueError(f"must be an integer from {low} to {high}")
        return int(number)

    return parse


def _number(low, high):
    def parse(value):
        number = float(value)
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"must be a number from {low:g} to {high:g}")
        return number

    return parse


def _flag(value):
    if value.lower() in {"1", "true", "on", "yes"}:
        return True
    if value.lower() in {"0", "false", "off", "no"}:
        return False
    raise ValueError("must be on or off")


def _choice(*names):
    def parse(value):
        if value not in names:
            raise ValueError("must be one of " + ", ".join(names))
        return value

    return parse


# key: (parser, one-line help). Values are normalized by the parser.
OPTIONS = {
    "aq": (_integer(1, 15), "Spatial adaptive quantization strength (1-15); off when unset"),
    "temporalaq": (_flag, "Temporal adaptive quantization (on/off)"),
    "multipass": (_choice("disabled", "qres", "fullres"), "Two-pass rate control; adds latency"),
    "qmax": (_integer(MIN_QP, MAX_QP), "Highest QP rate control may use (lower keeps quality)"),
    "vbv_frames": (_number(0.5, 8), "Rate buffer size in frames of data (default 1)"),
    "gop_seconds": (_number(1, 60), "Seconds between periodic IDR frames (default 10)"),
}


def parse_extra(text):
    """Return validated advanced settings from ``key=value`` lines or commas."""
    if text in (None, ""):
        return {}
    if not isinstance(text, str) or len(text) > MAX_EXTRA:
        raise ValueError("Advanced encoder settings must be short text")
    parsed = {}
    for item in text.replace(",", "\n").replace(";", "\n").splitlines():
        item = item.strip()
        if not item or item.startswith("#"):
            continue
        key, separator, value = item.partition("=")
        key, value = key.strip().lower(), value.strip()
        if not separator or not value:
            raise ValueError(f"Advanced setting '{item}' must look like key=value")
        if key in PROTECTED:
            raise ValueError(f"'{key}' cannot be changed: {PROTECTED[key]}")
        if key not in OPTIONS:
            raise ValueError(f"Unknown encoder setting '{key}'; choose from " + ", ".join(OPTIONS))
        if key in parsed:
            raise ValueError(f"Encoder setting '{key}' is repeated")
        try:
            parsed[key] = OPTIONS[key][0](value)
        except ValueError as exc:
            raise ValueError(f"Encoder setting '{key}' {exc}") from None
    return parsed


def automatic_bitrate(width, height):
    """Bitrate limit in Mbps for a stream that did not choose one.

    About the picture quality of the former constant-QP 24 default on IMX274 and
    simulation footage, at roughly half its bandwidth on camera footage. Easy
    scenes use less than the limit. Mirrored in stream-settings.js.
    """
    pixels = width * height
    if pixels <= 1280 * 720:
        return 5.0
    if pixels <= 1920 * 1080:
        return 10.0
    if pixels <= 2560 * 1440:
        return 16.0
    return 30.0


def bitrate(config, width, height):
    """The stream's bitrate limit in Mbps, resolving the automatic setting."""
    return config.bitrate_mbps or automatic_bitrate(width, height)


def validate(rate_control, bitrate_mbps, qp):
    if rate_control not in RATE_CONTROLS:
        raise ValueError("Choose a supported rate control")
    if rate_control == "cqp":
        if type(qp) is not int or not MIN_QP <= qp <= MAX_QP:
            raise ValueError(f"QP must be an integer from {MIN_QP} to {MAX_QP}")
    elif type(bitrate_mbps) not in (int, float) or not (
        bitrate_mbps == AUTOMATIC or MIN_MBPS <= bitrate_mbps <= MAX_MBPS
    ):
        raise ValueError(
            f"Bitrate must be from {MIN_MBPS:g} to {MAX_MBPS:g} Mbps, or {AUTOMATIC} for automatic"
        )
