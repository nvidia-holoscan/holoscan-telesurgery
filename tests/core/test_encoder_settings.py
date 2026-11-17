# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest
from telesurgery_core.video.codecs import encoder_options
from telesurgery_core.video.config import Config
from telesurgery_core.video.encoder_settings import (
    OPTIONS,
    PROTECTED,
    automatic_bitrate,
    parse_extra,
)


def test_default_limits_each_frame_to_its_share_without_nvenc_filler():
    options = encoder_options(Config(bitrate_mbps=12, fps=30), 1920, 1080)
    # NVENC's CBR mode pads H.264 with filler; VBR with peak == average does not.
    assert options["rc"] == "vbr" and options["bitrate"] == options["maxbitrate"] == 12_000_000
    assert options["vbvbufsize"] == options["vbvinit"] == 400_000
    assert options["gop"] == options["idrperiod"] == 300
    assert options["bf"] == 0 and options["lookahead"] == 0
    assert options["extra_output_delay"] == 0
    assert not {"aq", "multipass", "qmax", "temporalaq", "constqp"} & options.keys()


@pytest.mark.parametrize(
    "size,mbps",
    [((640, 480), 5), ((1280, 720), 5), ((1920, 1080), 10), ((2560, 1440), 16), ((3840, 2160), 30)],
)
def test_automatic_bitrate_follows_the_resolution(size, mbps):
    assert automatic_bitrate(*size) == mbps
    assert encoder_options(Config(), *size)["bitrate"] == mbps * 1_000_000
    assert encoder_options(Config(bitrate_mbps=7), *size)["bitrate"] == 7_000_000


def test_average_bitrate_allows_twice_the_peak_and_constant_qp_has_no_budget():
    vbr = encoder_options(Config(rate_control="vbr", bitrate_mbps=10, fps=30), 1920, 1080)
    assert (vbr["rc"], vbr["bitrate"], vbr["maxbitrate"]) == ("vbr", 10_000_000, 20_000_000)
    assert vbr["vbvbufsize"] == round(20_000_000 / 30)
    cqp = encoder_options(Config(rate_control="cqp", qp=28), 1920, 1080)
    assert (cqp["rc"], cqp["constqp"]) == ("constqp", "28")
    assert not {"bitrate", "maxbitrate", "vbvbufsize", "vbvinit"} & cqp.keys()


def test_advanced_settings_reach_the_encoder():
    config = Config(
        fps=30,
        encoder_extra="aq=8\ntemporalaq=on, multipass=qres\nqmax=40\nvbv_frames=2\ngop_seconds=5",
    )
    options = encoder_options(config, 1920, 1080)
    assert (options["aq"], options["multipass"], options["qmax"]) == ("8", "qres", "40")
    assert options["temporalaq"] == "1"
    assert options["vbvbufsize"] == round(10_000_000 / 30 * 2)
    assert options["gop"] == options["idrperiod"] == 150
    # The binding enables temporal AQ for any value, so "off" must omit the key.
    assert "temporalaq" not in encoder_options(Config(encoder_extra="temporalaq=off"), 1920, 1080)
    # The priority area's strength is applied by the codec, not passed to NVENC.
    assert parse_extra("area_strength=subtle") == {"area_strength": "subtle"}
    assert parse_extra("area_strength=strong") == {"area_strength": "strong"}
    assert "area_strength" not in encoder_options(
        Config(encoder_extra="area_strength=subtle"), 1920, 1080
    )


def test_priority_area_plan_for_each_strength_and_rate_control():
    import numpy as np
    from telesurgery_core.video.codecs import area_plan

    quarter = np.zeros((160, 285), dtype=np.uint8)
    quarter[:80, :] = 1
    quarter[:, 143:] = 0  # 80 rows of 143 columns: a quarter of the grid
    share = quarter.mean()
    # Default: the area 16 QP finer than the rest, which keeps a fifth of its bitrate.
    inside, outside, rate = area_plan(Config(), quarter)
    assert (inside, outside) == (2, 4)
    assert rate == pytest.approx(share + (1 - share) * 0.2) and 0.39 < rate < 0.41
    assert area_plan(Config(rate_control="vbr"), quarter) == (inside, outside, rate)
    # A larger area leaves less to save; the whole picture saves nothing.
    assert area_plan(Config(), np.ones((160, 285), dtype=np.uint8)) == (2, 4, 1.0)
    # Subtle never changes the bitrate.
    assert area_plan(Config(encoder_extra="area_strength=subtle"), quarter) == (1, 3, 1.0)
    # Constant QP has no bitrate to change.
    assert area_plan(Config(rate_control="cqp"), quarter) == (1, 4, 1.0)
    assert area_plan(Config(rate_control="cqp", encoder_extra="area_strength=subtle"), quarter) == (
        1,
        0,
        1.0,
    )


@pytest.mark.parametrize("key", sorted(PROTECTED))
def test_pipeline_settings_cannot_be_overridden(key):
    with pytest.raises(ValueError, match="cannot be changed"):
        parse_extra(f"{key}=1")


@pytest.mark.parametrize(
    "text",
    [
        "unknown=1",
        "aq",
        "aq=",
        "aq=0",
        "aq=16",
        "aq=1.5",
        "aq=8\naq=9",
        "multipass=full",
        "temporalaq=maybe",
        "qmax=60",
        "vbv_frames=0",
        "gop_seconds=nan",
        "area_strength=maximum",
        "area_strength=standard",
        "x" * 600,
    ],
)
def test_bad_advanced_settings_are_rejected_not_ignored(text):
    with pytest.raises(ValueError):
        parse_extra(text)


def test_blank_lines_and_comments_are_allowed_and_every_option_is_documented():
    assert parse_extra(None) == parse_extra("") == {}
    assert parse_extra("\n# try this\nAQ = 8\n") == {"aq": 8}
    assert all(help_text for _, help_text in OPTIONS.values())
