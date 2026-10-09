# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physical tool commands are validated before reaching the native FCI loop."""

import math
from types import SimpleNamespace

import pytest
from telesurgery_robots.franka.adapter import Franka


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
