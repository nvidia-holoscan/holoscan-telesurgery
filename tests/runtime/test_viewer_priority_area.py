# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Holoviz picture shows the priority area's outline and lends stills to draw on."""

import os
import time
from dataclasses import asdict

import cv2
import numpy as np
import pytest
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video import region
from telesurgery_core.video.codecs import create_codec
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame
from telesurgery_core.video.view import settings as zoom_settings

pytestmark = pytest.mark.gpu

WIDTH, HEIGHT = 640, 480
BGR = [20, 90, 170]  # shown as RGB 170, 90, 20
BOX = [[0.3, 0.3], [0.7, 0.3], [0.7, 0.7], [0.3, 0.7]]


class Stream:
    """One camera's encoder feeding the native viewer's decode stage."""

    def __init__(self, codec, width=WIDTH, height=HEIGHT):
        from telesurgery_runtime.application.viewer import ReceiveDecode

        self.size = (width, height)
        self.encoder = create_codec(Config(codec=codec, width=width, height=height), encode=True)
        self.viewer = ReceiveDecode()
        self.viewer.start()
        self.sequence = 0

    def show(self):
        """Encode one flat frame and return what the viewer hands to Holoviz, on the host."""
        width, height = self.size
        pixels = np.full((height, width, 3), BGR, dtype=np.uint8)
        header, data = self.encoder.encode(
            Frame(VideoHeader(self.sequence, time.time_ns(), width, height), pixels)
        )
        self.sequence += 1
        self.viewer.put(asdict(header), data)
        return self.viewer.compute().get()

    def close(self):
        self.viewer.stop()
        self.encoder.close()


def colours(image, indices):
    return image.reshape(-1, 3)[indices]


@pytest.mark.parametrize("codec", ["h264", "h265", "nvjpeg", "raw-bgr8"])
def test_holoviz_picture_carries_the_outline_and_is_untouched_without_an_area(codec):
    stream = Stream(codec)
    try:
        halo, line = region.outline(BOX, WIDTH, HEIGHT)
        plain = stream.show()
        np.testing.assert_allclose(colours(plain, halo), [[170, 90, 20]] * halo.size, atol=6)

        stream.viewer.outline = (WIDTH, HEIGHT, halo, line)
        image = stream.show()
        assert (colours(image, line) == region.OUTLINE_LINE).all()
        around = np.setdiff1d(halo, line)
        assert (colours(image, around) == region.OUTLINE_HALO).all()
        # Only the outline is drawn: the picture inside and outside the area is as decoded.
        untouched = np.ones(WIDTH * HEIGHT, dtype=bool)
        untouched[halo] = False
        np.testing.assert_array_equal(
            image.reshape(-1, 3)[untouched], plain.reshape(-1, 3)[untouched]
        )

        # Zoom crops the frame after the outline is drawn, so the two stay registered.
        stream.viewer.zoom = zoom_settings(2.0, 0.5, 0.5)
        zoomed = stream.show()
        assert zoomed.shape == (HEIGHT // 2, WIDTH // 2, 3)
        left = round((0.3 - 0.25) * WIDTH)  # the area's left edge inside the 0.25-0.75 crop
        row = zoomed[HEIGHT // 4, left - 4 : left + 4]
        assert (row == region.OUTLINE_LINE).all(axis=1).sum() == 2
        np.testing.assert_allclose(zoomed[HEIGHT // 4, WIDTH // 4], [170, 90, 20], atol=6)
        stream.viewer.zoom = zoom_settings()

        # An outline computed for another picture size is not drawn on this one.
        stream.viewer.outline = (WIDTH * 2, HEIGHT * 2, *region.outline(BOX, WIDTH * 2, HEIGHT * 2))
        np.testing.assert_array_equal(stream.show(), plain)

        # A depth-only view replaces the colour picture; the outline is drawn on it instead.
        stream.viewer.outline = (WIDTH, HEIGHT, halo, line)
        stream.viewer.display = {"mode": "depth", "distance": 2.0, "opacity": 0.4}
        depth = stream.show()
        assert (colours(depth, line) == region.OUTLINE_LINE).all()
        assert not depth[HEIGHT // 2, WIDTH // 2].any()
        stream.viewer.display = {"mode": "color", "distance": 2.0, "opacity": 0.4}

        # Cleared: the next frame is plain again.
        stream.viewer.outline = None
        np.testing.assert_array_equal(stream.show(), plain)
    finally:
        stream.close()


@pytest.mark.parametrize("width,height", [(1920, 1080), (3840, 2160)])
def test_outline_is_visible_at_camera_resolutions(width, height):
    stream = Stream("h265", width, height)
    try:
        halo, line = region.outline(BOX, width, height)
        stream.viewer.outline = (width, height, halo, line)
        image = stream.show()
        assert (colours(image, line) == region.OUTLINE_LINE).all()
        # About 2 picture lines per 1080, so it survives scaling to a smaller window.
        column = image[: height // 2, width // 2]
        assert (column == region.OUTLINE_LINE).all(axis=1).sum() == height // 540
    finally:
        stream.close()


# The small picture is lent whole (no reduction), which must still be a copy.
@pytest.mark.parametrize(
    "width,height,still_size", [(1920, 1080, (360, 640)), (640, 480, (480, 640))]
)
def test_still_is_lent_while_asked_without_the_outline_and_stops_when_the_asking_stops(
    tmp_path, width, height, still_size
):
    from telesurgery_runtime.application.viewer import (
        STILL_REQUEST_SECONDS,
        Stills,
        still_wanted,
    )

    stream = Stream("h264", width, height)
    still, request = tmp_path / "preview.jpg", tmp_path / "preview-request"
    try:
        viewer = stream.viewer
        viewer.stills = Stills(still)
        viewer.outline = (width, height, *region.outline(BOX, width, height))
        # Nobody asked: frames are shown and no still is produced.
        assert not still_wanted(request)
        for _ in range(3):
            stream.show()
        viewer.stills.worker.submit(lambda: None).result()
        assert not still.exists() and viewer.stills.written == 0

        request.touch()
        viewer.stills.want(still_wanted(request))
        assert viewer.stills.wanted
        deadline = time.monotonic() + 5
        while viewer.stills.written < 3 and time.monotonic() < deadline:
            stream.show()
            time.sleep(0.02)
        elapsed = time.monotonic() - (deadline - 5)
        picture = cv2.imread(str(still))
        # The full picture, small, in its own colours: the outline is not burned in, because
        # the dashboard draws its own over the still.
        rows, columns = still_size
        assert picture.shape == (rows, columns, 3)
        np.testing.assert_allclose(picture[rows // 2, columns // 2], BGR, atol=8)
        # Along the area's top edge and at its corner, where the outline would be.
        for row, column in ((0.3, 0.5), (0.3, 0.3), (0.5, 0.7)):
            np.testing.assert_allclose(
                picture[round(row * rows), round(column * columns)], BGR, atol=8
            )
        # Paced: no more than about four a second however fast frames arrive.
        assert viewer.stills.written <= elapsed / Stills.INTERVAL + 1
        # The outline is still in the picture Holoviz shows.
        line = viewer.outline[3]
        assert (colours(stream.show(), line) == region.OUTLINE_LINE).all()

        # The dashboard stopped asking: the old still is removed and no new one appears.
        os.utime(request, (time.time() - STILL_REQUEST_SECONDS - 1,) * 2)
        viewer.stills.want(still_wanted(request))
        written = viewer.stills.written
        for _ in range(20):
            stream.show()
            time.sleep(0.02)
        viewer.stills.worker.submit(lambda: None).result()
        assert not still.exists() and viewer.stills.written == written
    finally:
        stream.close()
    assert not still.exists()
