# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A priority area is one bounded polygon; the encoder receives the cells inside it."""

import json

import numpy as np
import pytest
from telesurgery_core.video import region

BOX = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]


def test_mask_matches_the_encoder_grid_and_fills_cells_whose_centre_is_inside():
    mask = region.mask(BOX)
    assert mask.shape == (160, 285) == (region.GRID_ROWS, region.GRID_COLUMNS)
    assert mask.dtype == np.uint8 and mask.flags.c_contiguous
    assert set(np.unique(mask)) == {0, 1}
    rows, columns = np.nonzero(mask)
    # Cell centres are (index + 0.5) / size: rows 40-119 and columns 71-213 lie in the box.
    assert (rows.min(), rows.max(), columns.min(), columns.max()) == (40, 119, 71, 213)
    assert mask.sum() == 80 * 143
    # Drawing direction does not matter.
    assert np.array_equal(region.mask(BOX[::-1]), mask)


def test_mask_covers_the_whole_picture_and_stays_inside_it_at_the_edges():
    assert region.mask([[0, 0], [1, 0], [1, 1], [0, 1]]).all()
    corner = region.mask([[0, 0], [0.5, 0], [0, 0.5]])
    assert corner[0, 0] == 1 and corner[0, 141] == 1 and corner[79, 0] == 1
    assert corner[0, 143] == 0 and corner[81, 0] == 0 and corner[80, 142] == 0
    right = region.mask([[0.9, 0.1], [1, 0.1], [1, 0.9], [0.9, 0.9]])
    assert right[:, -1].sum() == 128 and right[:, :256].sum() == 0


def test_mask_follows_concave_and_self_crossing_outlines():
    letter = region.mask([[0.1, 0.1], [0.9, 0.1], [0.9, 0.4], [0.4, 0.4], [0.4, 0.9], [0.1, 0.9]])
    assert letter[20, 30] and letter[30, 200] and letter[120, 50]
    assert not letter[120, 200]  # the notch of the L stays outside
    # A lasso that crosses itself still fills both loops it encloses.
    bow = region.mask([[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]])
    assert bow[80, 40] and bow[80, 244] and not bow[20, 142] and not bow[140, 142]
    assert bow.mean() == pytest.approx(0.32, abs=0.01)


def test_mask_scales_to_other_grids():
    assert region.mask(BOX, rows=4, columns=8).tolist() == [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]


def test_validate_normalizes_and_bounds_a_polygon():
    assert region.validate([(0.123456, 0.2), (0.8, 0.2), (0.5, 0.80004)]) == [
        [0.1235, 0.2],
        [0.8, 0.2],
        [0.5, 0.8],
    ]
    assert len(region.validate([[i / 63, (i % 2) * 0.5] for i in range(64)])) == 64
    for bad, message in (
        (None, "3 to 64 points"),
        ("box", "3 to 64 points"),
        ([[0.1, 0.1], [0.9, 0.9]], "3 to 64 points"),
        ([[i / 100, 0.5] for i in range(65)], "3 to 64 points"),
        ([[0.1, 0.1], [0.9, 0.1], [0.5]], "inside the picture"),
        ([[0.1, 0.1], [0.9, 0.1], "0.5,0.9"], "inside the picture"),
        ([[0.1, 0.1], [0.9, 0.1], [0.5, 1.01]], "inside the picture"),
        ([[0.1, 0.1], [0.9, 0.1], [-0.01, 0.9]], "inside the picture"),
        ([[0.1, 0.1], [0.9, 0.1], [0.5, float("nan")]], "inside the picture"),
        ([[0.1, 0.1], [0.9, 0.1], [0.5, float("inf")]], "inside the picture"),
        ([[0.1, 0.1], [0.9, 0.1], [True, 0.9]], "inside the picture"),
        ([[0.1, 0.1], [0.9, 0.1], ["0.5", 0.9]], "inside the picture"),
        # Smaller than half a percent of the picture, and a line with no inside.
        ([[0.5, 0.5], [0.55, 0.5], [0.55, 0.55], [0.5, 0.55]], "larger"),
        ([[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]], "larger"),
    ):
        with pytest.raises(ValueError, match=message):
            region.validate(bad)
    # Half a percent is enough.
    region.validate([[0.5, 0.5], [0.58, 0.5], [0.58, 0.58], [0.5, 0.58]])


def test_stream_settings_that_rule_out_an_area_are_named():
    assert region.unavailable("h264") == region.unavailable("h265", "qmax=40") == ""
    assert region.unavailable("h264", "temporalaq=off") == ""
    for codec in ("nvjpeg", "raw-bgr8", "surgical-tokenizer"):
        assert "H.264 or H.265" in region.unavailable(codec)
    for extra in ("aq=8", "temporalaq=on", "aq=1, temporalaq=on"):
        assert "adaptive quantization" in region.unavailable("h264", extra)
    # Settings that fail validation are reported where they are saved, not here.
    assert region.unavailable("h264", "nonsense") == ""


def test_request_and_status_files_are_replaced_whole(tmp_path):
    request, status = tmp_path / "camera.region", tmp_path / "camera.region-status"
    assert region.stamp(request) is None
    assert region.read_request(request) == (None, None)
    assert region.read_status(status) == {}
    region.write_request(request, 3, BOX)
    first = region.stamp(request)
    assert region.read_request(request) == (3, BOX)
    region.write_request(request, 4, None)
    assert region.stamp(request) != first  # a new file, even within one clock tick
    assert region.read_request(request) == (4, None)
    assert [path.name for path in tmp_path.iterdir()] == ["camera.region"]
    # A damaged or out-of-range request means no area rather than a wrong one.
    request.write_text("{")
    assert region.read_request(request) == (None, None)
    request.write_text(json.dumps({"revision": 5, "points": [[0, 0], [2, 0], [0, 2]]}))
    assert region.read_request(request) == (5, None)
    request.write_text("[]")
    assert region.read_request(request) == (None, None)
    region.write_status(status, True, "", 4)
    assert region.read_status(status) == {
        "supported": True,
        "blocked": "",
        "revision": 4,
        "error": "",
    }
    region.write_status(status, 0, "it needs an H.264 or H.265 stream", None, "refused")
    assert region.read_status(status) == {
        "supported": False,
        "blocked": "it needs an H.264 or H.265 stream",
        "revision": None,
        "error": "refused",
    }


@pytest.mark.parametrize(
    "width,height,line,halo",
    [(1280, 720, 2, 4), (1920, 1080, 3, 7), (3840, 2160, 6, 12)],
)
def test_outline_is_a_line_with_a_halo_scaled_to_the_picture(width, height, line, halo):
    box = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
    dark, bright = region.outline(box, width, height)
    for indices in (dark, bright):
        assert indices.dtype == np.int32
        assert np.all(np.diff(indices) > 0)  # sorted, each pixel once
        assert 0 <= indices[0] and indices[-1] < width * height
    assert np.isin(bright, dark).all()
    picture = np.zeros(width * height, dtype=np.uint8)
    picture[dark] = 1
    picture[bright] = 2
    picture = picture.reshape(height, width)
    # Crossing the top edge at the middle of the picture: halo, line, halo.
    column = picture[: height // 2, width // 2]
    assert (column == 2).sum() == line and (column > 0).sum() == halo
    top = np.flatnonzero(column == 2)
    assert abs(top.mean() - height * 0.25) <= line
    # Crossing the left edge at mid-height, and nothing drawn inside or outside the box.
    row = picture[height // 2, : width // 2]
    assert (row == 2).sum() == line and (row > 0).sum() == halo
    assert not picture[height // 2, width // 2] and not picture[5, 5]
    # A closed outline: every row between the top and bottom edges crosses it twice.
    rows = picture[int(height * 0.3) : int(height * 0.7)]
    assert ((rows == 2).sum(axis=1) == 2 * line).all()


def test_outline_follows_slanted_edges_without_gaps_and_stays_inside_the_picture():
    width, height = 640, 360
    triangle = [[0.0, 0.0], [1.0, 0.4], [0.3, 1.0]]
    dark, bright = region.outline(triangle, width, height)
    picture = np.zeros(width * height, dtype=bool)
    picture[bright] = True
    picture = picture.reshape(height, width)
    # Each row and each column the triangle spans holds part of the line.
    assert picture.any(axis=1).all() and picture.any(axis=0).all()
    assert picture[0, 0] and picture[height - 1, int(0.3 * width)]
    # Points on the picture's border are drawn at the border, not wrapped to the other side.
    edge = region.outline([[0, 0], [1, 0], [1, 1], [0, 1]], width, height)[1]
    border = np.zeros(width * height, dtype=bool)
    border[edge] = True
    border = border.reshape(height, width)
    assert border[0].all() and border[-1].all() and border[:, 0].all() and border[:, -1].all()
    assert not border[height // 2, width // 2]
