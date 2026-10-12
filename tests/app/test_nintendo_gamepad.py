# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise Switch 2 HID mappings through a real SDL virtual joystick."""

import ctypes as c
from ctypes.util import find_library

import pytest
from telesurgery.controller.gamepad import SWITCH2_MAPPING, Gamepads


def test_switch2_sticks_and_buttons_through_sdl():
    if not find_library("SDL2-2.0"):
        pytest.skip("SDL2 is unavailable")
    pads = Gamepads()
    sdl = pads.sdl
    signatures = {
        "SDL_JoystickAttachVirtual": ([c.c_int, c.c_int, c.c_int, c.c_int], c.c_int),
        "SDL_JoystickDetachVirtual": ([c.c_int], c.c_int),
        "SDL_JoystickOpen": ([c.c_int], c.c_void_p),
        "SDL_JoystickClose": ([c.c_void_p], None),
        "SDL_JoystickSetVirtualAxis": ([c.c_void_p, c.c_int, c.c_int16], c.c_int),
        "SDL_JoystickSetVirtualButton": ([c.c_void_p, c.c_int, c.c_uint8], c.c_int),
    }
    for name, (args, result) in signatures.items():
        function = getattr(sdl, name)
        function.argtypes, function.restype = args, result
    index = sdl.SDL_JoystickAttachVirtual(0, 4, 21, 0)
    assert index >= 0
    joystick = None
    try:
        guid = c.create_string_buffer(33)
        sdl.SDL_JoystickGetGUIDString(sdl.SDL_JoystickGetDeviceGUID(index), guid, 33)
        assert sdl.SDL_GameControllerAddMapping(guid.value + b"," + SWITCH2_MAPPING.encode()) >= 0
        joystick = sdl.SDL_JoystickOpen(index)
        assert joystick
        pads.select(sdl.SDL_JoystickGetDeviceInstanceID(index))
        for axis, value in enumerate((16384, 8192, -16384, -8192)):
            assert sdl.SDL_JoystickSetVirtualAxis(joystick, axis, value) == 0
        axes, buttons = pads.sample()
        assert axes == pytest.approx([0.5, -0.25, -0.5, 0.25], abs=0.0001)
        assert buttons == set()
        # Standard web positions: south/east/west/north, shoulders, Start,
        # D-pad up/down/left/right, and Home. Extra C/GL/GR are not robot inputs.
        for raw, web in [
            (0, 0),
            (1, 1),
            (2, 2),
            (3, 3),
            (12, 4),
            (4, 5),
            (6, 9),
            (11, 12),
            (8, 13),
            (10, 14),
            (9, 15),
            (16, 16),
            (18, None),
            (19, None),
            (20, None),
        ]:
            sdl.SDL_JoystickSetVirtualButton(joystick, raw, 1)
            assert pads.sample()[1] == ({web} if web is not None else set())
            sdl.SDL_JoystickSetVirtualButton(joystick, raw, 0)
            assert pads.sample()[1] == set()
        pads.select(None)
        sdl.SDL_JoystickClose(joystick)
        joystick = None
        assert sdl.SDL_JoystickDetachVirtual(index) == 0
        index = -1
        assert pads.sample() is None
    finally:
        pads.select(None)
        if joystick:
            sdl.SDL_JoystickClose(joystick)
        if index >= 0:
            sdl.SDL_JoystickDetachVirtual(index)
        pads.close()
