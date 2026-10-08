# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""GPU conversion contracts used by codecs and IMX274 capture."""

import numpy as np
import pytest
from telesurgery_core.video.gpu import demosaic, nv12

pytestmark = pytest.mark.gpu
cp = pytest.importorskip("cupy")


@pytest.mark.parametrize("pattern", range(4))
def test_bayer_patterns_preserve_channels_at_boundaries(pattern):
    grids = ((0, 1, 1, 2), (2, 1, 1, 0), (1, 0, 2, 1), (1, 2, 0, 1))
    colors = np.array([4096, 32768, 61440], dtype=np.uint16)
    grid = colors[list(grids[pattern])].reshape(2, 2)
    bayer = cp.asarray(np.tile(grid, (9, 13)))
    result = cp.asnumpy(demosaic(cp, bayer, pattern))
    np.testing.assert_array_equal(result, np.broadcast_to([71, 188, 248], (18, 26, 3)))


@pytest.mark.parametrize("width,height", [(640, 480), (1920, 1080)])
def test_nv12_strided_input_matches_scalar_color_equations(width, height):
    rng = np.random.default_rng(4)
    rgb = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    bgr = rgb[..., ::-1]
    device = cp.asarray(rgb)[..., ::-1]
    result = cp.asnumpy(nv12(cp, device))
    b, g, r = (bgr[..., i].astype(np.float32) for i in range(3))
    if width <= 720 and height <= 576:
        y = 16 + 0.257 * r + 0.504 * g + 0.098 * b
        u, v = 128 - 0.148 * r - 0.291 * g + 0.439 * b, 128 + 0.439 * r - 0.368 * g - 0.071 * b
    else:
        y = 16 + 0.183 * r + 0.614 * g + 0.062 * b
        u, v = 128 - 0.101 * r - 0.339 * g + 0.439 * b, 128 + 0.439 * r - 0.399 * g - 0.040 * b
    expected = np.empty_like(result)
    expected[:height] = np.clip(np.rint(y), 16, 235)
    for offset, plane in enumerate((u, v)):
        plane = plane.reshape(height // 2, 2, width // 2, 2).mean(axis=(1, 3))
        expected[height:, offset::2] = np.clip(np.rint(plane), 16, 240)
    # Floating-point association may differ at exactly half-integer rounding.
    assert np.abs(result.astype(int) - expected.astype(int)).max() <= 1


def test_linear_camera_display_transfer_preserves_black_white_and_dark_detail():
    # sRGB reference values: black, linear toe, 18% gray, 50% gray, white.
    for level, expected in zip([0, 128, 11796, 32768, 65535], [0, 6, 118, 188, 255], strict=True):
        bayer = cp.full((4, 4), level, dtype=cp.uint16)
        result = cp.asnumpy(demosaic(cp, bayer, 0))
        assert result.shape == (4, 4, 3)
        assert np.all(result == expected)
