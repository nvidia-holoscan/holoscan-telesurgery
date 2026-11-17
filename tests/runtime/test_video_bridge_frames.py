# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The surgeon's browser path keeps predicted frames in order."""

from telesurgery_runtime.application.pipeline import Deliver, Frames


def test_predicted_frames_stay_in_order_and_cameras_take_turns():
    frames = Frames(backlog=3)
    frames.put("one", "idr", keyframe=True)
    frames.put("one", "p1", keyframe=False)
    frames.put("two", "idr2", keyframe=True)
    frames.put("one", "p2", keyframe=False)
    assert [frames.compute() for _ in range(5)] == ["idr", "idr2", "p1", "p2", None]


def test_a_keyframe_replaces_the_backlog_and_an_overflow_drops_it():
    frames = Frames(backlog=3)
    # Intra-only streams mark every frame a keyframe: only the newest is kept.
    for name in ("jpeg1", "jpeg2", "jpeg3"):
        frames.put("camera", name)
    assert [frames.compute(), frames.compute()] == ["jpeg3", None]
    # A new IDR makes the predicted frames before it unnecessary.
    for name, keyframe in (("p1", False), ("p2", False), ("idr", True), ("p3", False)):
        frames.put("camera", name, keyframe)
    assert [frames.compute(), frames.compute()] == ["idr", "p3"]
    # Too far behind: the old backlog is dropped, and the receiver will ask for an IDR.
    for name in ("p4", "p5", "p6", "p7"):
        frames.put("camera", name, keyframe=False)
    assert [frames.compute(), frames.compute()] == ["p7", None]


def test_delivery_drains_every_waiting_frame_even_when_a_wake_up_is_dropped():
    frames, delivered = Frames(), []
    sink, wake = Deliver(delivered.append, frames), frames.wake
    assert wake.compute() is None
    for name, keyframe in (("idr", True), ("p1", False), ("p2", False)):
        frames.put("camera", name, keyframe)
    # The graph edge keeps one message: several ticks may reach the sink as one.
    assert wake.compute() is True and wake.compute() is True
    sink.compute(True)
    assert delivered == ["idr", "p1", "p2"] and sink.frames == 3
    assert wake.compute() is None
    sink.compute(True)  # A late wake-up finds nothing and is harmless.
    assert delivered == ["idr", "p1", "p2"]
