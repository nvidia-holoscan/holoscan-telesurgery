# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physical tool commands are validated before reaching the native FCI loop."""

import math
from types import SimpleNamespace

import pytest
from telesurgery_robots.franka.adapter import Franka
from telesurgery_robots.workspace import Workspace


def test_measured_pose_has_the_shared_cartesian_feedback_shape():
    from telesurgery.controller.haply import CartesianHaply

    # A non-symmetric rotation catches row/column layout mistakes.
    matrix = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0.4, -0.2, 0.3, 1]
    state = {
        "q": [0] * 7,
        "dq": [0] * 7,
        "tau_J": [0] * 7,
        "O_T_EE": matrix,
        "F_T_EE": matrix,
        "EE_T_K": matrix,
        "mode": "idle",
        "faults": "[]",
        "device_time_ms": 1,
        "control_active": False,
        "home_active": False,
        "stopping": False,
    }
    adapter = Franka.__new__(Franka)
    adapter.workspace = Workspace()
    adapter.tool_frames = None
    adapter.reader = SimpleNamespace(
        read=lambda: state, kinematics=lambda *args: (matrix, [0] * 42)
    )
    feedback = adapter.read()
    position, orientation = CartesianHaply.pose(feedback)
    assert position.tolist() == [0.4, -0.2, 0.3]
    assert orientation.tolist() == [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    assert feedback["tool_pose"]["matrix"] == matrix


@pytest.mark.parametrize("axis", range(6))
@pytest.mark.parametrize("sign", [-1, 1])
def test_physical_tool_axes_and_speed_reach_native_loop(axis, sign):
    moves = []
    adapter = Franka.__new__(Franka)
    adapter.read = lambda: {"control_active": True}
    adapter.reader = SimpleNamespace(
        jog_cartesian=lambda command, **kw: moves.append((command, kw))
    )
    twist = [0] * 6
    twist[axis] = sign
    result = adapter.jog({"translation": twist[:3], "rotation": twist[3:]}, speed_deg_s=4)
    assert result["control_active"]
    assert moves == [(twist, {"speed": pytest.approx(math.radians(4))})]


@pytest.mark.parametrize(
    "command,speed",
    [
        ({"translation": [True, 0, 0], "rotation": [0, 0, 0]}, 4),
        ({"translation": [float("nan"), 0, 0], "rotation": [0, 0, 0]}, 4),
        ({"translation": [1.1, 0, 0], "rotation": [0, 0, 0]}, 4),
        ({"translation": [1, 0], "rotation": [0, 0, 0]}, 4),
        ({"translation": [1, 0, 0]}, 4),
        ({"translation": [1, 0, 0], "rotation": [0, 0, 0], "joints": [0] * 7}, 4),
        ({"translation": [1, 0, 0], "rotation": [0, 0, 0]}, 21),
    ],
)
def test_invalid_tool_commands_never_open_hardware(command, speed):
    adapter = Franka.__new__(Franka)
    adapter.read = lambda: pytest.fail("Invalid request reached hardware")
    with pytest.raises(ValueError):
        adapter.jog(command, speed_deg_s=speed)
