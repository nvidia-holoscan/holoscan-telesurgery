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


def test_default_uses_cbr_with_a_one_frame_vbv():
    options = encoder_options(Config(bitrate_mbps=12, fps=30), 1920, 1080)
    assert (options["rc"], options["bitrate"]) == ("cbr", 12_000_000)
    assert "maxbitrate" not in options
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


def test_native_cbr_passes_average_only_and_uses_a_one_frame_vbv():
    config = Config(rate_control="cbr", bitrate_mbps=10, fps=60)
    options = encoder_options(config, 1920, 1080)
    assert (options["rc"], options["bitrate"]) == ("cbr", 10_000_000)
    assert "maxbitrate" not in options
    assert options["vbvbufsize"] == options["vbvinit"] == 166_667


def test_explicit_vbr_max_bitrate_controls_max_bitrate_and_vbv():
    config = Config(rate_control="vbr", bitrate_mbps=10, max_bitrate_mbps=13, fps=60)
    options = encoder_options(config, 1920, 1080)
    assert (options["rc"], options["bitrate"], options["maxbitrate"]) == (
        "vbr",
        10_000_000,
        13_000_000,
    )
    assert options["vbvbufsize"] == options["vbvinit"] == 216_667


@pytest.mark.parametrize("average", [0, 10])
def test_vbr_max_bitrate_must_cover_the_explicit_or_automatic_average(average):
    config = Config(rate_control="vbr", bitrate_mbps=average, max_bitrate_mbps=8)
    with pytest.raises(ValueError, match="Max bitrate must be at least the average bitrate"):
        encoder_options(config, 1920, 1080)


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
