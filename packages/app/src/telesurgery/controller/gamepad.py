# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SDL2 standard gamepads, normalized to the browser's button numbering."""

import ctypes as c
from ctypes.util import find_library

# SDL A/B/X/Y, shoulders, Start, D-pad, Guide -> Web Gamepad standard indices.
BUTTONS = {0: 0, 1: 1, 2: 2, 3: 3, 9: 4, 10: 5, 6: 9, 11: 12, 12: 13, 13: 14, 14: 15, 5: 16}


class Gamepads:
    def __init__(self):
        library = find_library("SDL2-2.0")
        if not library:
            raise RuntimeError("Gamepad support needs SDL2; run setup.sh")
        self.sdl = c.CDLL(library)
        signatures = {
            "SDL_SetHint": ([c.c_char_p, c.c_char_p], c.c_int),
            "SDL_InitSubSystem": ([c.c_uint32], c.c_int),
            "SDL_QuitSubSystem": ([c.c_uint32], None),
            "SDL_GetError": ([], c.c_char_p),
            "SDL_PumpEvents": ([], None),
            "SDL_GameControllerUpdate": ([], None),
            "SDL_NumJoysticks": ([], c.c_int),
            "SDL_IsGameController": ([c.c_int], c.c_int),
            "SDL_JoystickGetDeviceInstanceID": ([c.c_int], c.c_int32),
            "SDL_GameControllerNameForIndex": ([c.c_int], c.c_char_p),
            "SDL_GameControllerOpen": ([c.c_int], c.c_void_p),
            "SDL_GameControllerClose": ([c.c_void_p], None),
            "SDL_GameControllerGetAttached": ([c.c_void_p], c.c_int),
            "SDL_GameControllerGetAxis": ([c.c_void_p, c.c_int], c.c_int16),
            "SDL_GameControllerGetButton": ([c.c_void_p, c.c_int], c.c_uint8),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.sdl, name)
            function.argtypes, function.restype = arguments, result
        # Tk owns the desktop window. Input focus is enforced by the controller.
        self.sdl.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if self.sdl.SDL_InitSubSystem(0x2000) != 0:
            raise RuntimeError(self.sdl.SDL_GetError().decode(errors="replace"))
        self.handle = None
        self.selected = None

    def devices(self):
        self.sdl.SDL_PumpEvents()
        result = {}
        for index in range(self.sdl.SDL_NumJoysticks()):
            if self.sdl.SDL_IsGameController(index):
                identity = self.sdl.SDL_JoystickGetDeviceInstanceID(index)
                name = self.sdl.SDL_GameControllerNameForIndex(index) or b"Gamepad"
                result[identity] = (index, name.decode(errors="replace"))
        return result

    def select(self, identity):
        if self.handle:
            self.sdl.SDL_GameControllerClose(self.handle)
        self.handle = None
        self.selected = identity
        if identity is not None and identity in (devices := self.devices()):
            self.handle = self.sdl.SDL_GameControllerOpen(devices[identity][0])
            if not self.handle:
                raise RuntimeError(self.sdl.SDL_GetError().decode(errors="replace"))

    def sample(self):
        self.sdl.SDL_PumpEvents()
        self.sdl.SDL_GameControllerUpdate()
        if not self.handle or not self.sdl.SDL_GameControllerGetAttached(self.handle):
            return None
        axes = [self.sdl.SDL_GameControllerGetAxis(self.handle, i) / 32767 for i in range(4)]
        buttons = {
            web
            for sdl, web in BUTTONS.items()
            if self.sdl.SDL_GameControllerGetButton(self.handle, sdl)
        }
        return axes, buttons

    def close(self):
        self.select(None)
        self.sdl.SDL_QuitSubSystem(0x2000)
