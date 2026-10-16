# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""SDL2 standard gamepads, normalized to the browser's button numbering."""

import ctypes as c
import re
from ctypes.util import find_library

# SDL A/B/X/Y, shoulders, Start, D-pad, Guide -> Web Gamepad standard indices.
BUTTONS = {0: 0, 1: 1, 2: 2, 3: 3, 9: 4, 10: 5, 6: 9, 11: 12, 12: 13, 13: 14, 14: 15, 5: 16}


class GUID(c.Structure):
    _fields_ = [("data", c.c_uint8 * 16)]


# Linux's generic Switch 2 Pro HID report (0x09). Both sticks have upward-positive
# Y axes; map physical positions, not Nintendo's printed A/B and X/Y labels.
SWITCH2_MAPPING = (
    "Nintendo Pro Controller,a:b0,b:b1,x:b2,y:b3,"
    "leftshoulder:b12,rightshoulder:b4,lefttrigger:b13,righttrigger:b5,"
    "back:b14,start:b6,guide:b16,leftstick:b15,rightstick:b7,"
    "dpup:b11,dpdown:b8,dpleft:b10,dpright:b9,"
    "leftx:a0,lefty:a1~,rightx:a2,righty:a3~,platform:Linux,"
)


def controller_name(name):
    """Use the same short device names as the browser input selector."""
    if re.search(r"dualsense|ps5\b|054c.*0ce6", name, re.I):
        return "Sony DualSense"
    if re.search(r"dualshock|ps4\b|054c.*(05c4|09cc)", name, re.I):
        return "Sony DualShock 4"
    if re.search(r"playstation|ps3\b|054c", name, re.I):
        return "PlayStation controller"
    if re.search(r"nintendo|switch.*pro|joy.?con|057e", name, re.I):
        return "Nintendo controller"
    if re.search(r"xbox|x-box|xinput|microsoft.*controller|045e", name, re.I):
        return "Xbox controller"
    name = re.sub(r"\s*\([^)]*\)\s*", " ", name).strip()
    return name[:25] + "…" if len(name) > 26 else name or "Gamepad"


def controller_bindings(name):
    """Printed labels for the same physical buttons on each controller family."""
    if re.search(r"dualsense|dualshock|playstation|ps[345]\b|054c", name, re.I):
        labels = ("L1", "R1", "△", "✕", "□", "○", "PS button", "Options")
    elif re.search(r"nintendo|switch.*pro|joy.?con|057e", name, re.I):
        labels = ("L", "R", "X", "B", "Y", "A", "Home button", "+")
    elif re.search(r"xbox|x-box|xinput|microsoft.*controller|045e", name, re.I):
        labels = ("LB", "RB", "Y", "A", "X", "B", "Xbox button", "Menu ☰")
    else:
        labels = (
            "LB/L1",
            "RB/R1",
            "North",
            "South",
            "West",
            "East",
            "Guide button",
            "Start / Menu",
        )
    return dict(
        zip(
            (
                "enable",
                "alternate",
                "roll_up",
                "roll_down",
                "close",
                "open",
                "home",
                "home_fallback",
            ),
            labels,
            strict=True,
        )
    )


def controller_selection(devices, selected):
    if selected not in devices:
        return None
    name = controller_name(devices[selected][1])
    matching = [key for key, (_, raw) in devices.items() if controller_name(raw) == name]
    return {"name": name, "ordinal": matching.index(selected), "count": len(matching)}


class Gamepads:
    def __init__(self):
        library = find_library("SDL2-2.0")
        if not library:
            raise RuntimeError("Gamepad support needs SDL2; run setup.sh")
        self.sdl = c.CDLL(library)
        signatures = {
            "SDL_SetHint": ([c.c_char_p, c.c_char_p], c.c_int),
            "SDL_SetHintWithPriority": ([c.c_char_p, c.c_char_p, c.c_int], c.c_int),
            "SDL_InitSubSystem": ([c.c_uint32], c.c_int),
            "SDL_QuitSubSystem": ([c.c_uint32], None),
            "SDL_GetError": ([], c.c_char_p),
            "SDL_PumpEvents": ([], None),
            "SDL_GameControllerUpdate": ([], None),
            "SDL_NumJoysticks": ([], c.c_int),
            "SDL_IsGameController": ([c.c_int], c.c_int),
            "SDL_JoystickGetDeviceInstanceID": ([c.c_int], c.c_int32),
            "SDL_JoystickGetDeviceVendor": ([c.c_int], c.c_uint16),
            "SDL_JoystickGetDeviceProduct": ([c.c_int], c.c_uint16),
            "SDL_JoystickPathForIndex": ([c.c_int], c.c_char_p),
            "SDL_JoystickGetDeviceGUID": ([c.c_int], GUID),
            "SDL_JoystickGetGUIDString": ([GUID, c.c_char_p, c.c_int], None),
            "SDL_GameControllerAddMapping": ([c.c_char_p], c.c_int),
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
        # Keep Switch face buttons positional, matching the browser's standard
        # mapping; SDL2 otherwise defaults to Nintendo's swapped letter labels.
        self.sdl.SDL_SetHintWithPriority(b"SDL_GAMECONTROLLER_USE_BUTTON_LABELS", b"0", 2)
        if self.sdl.SDL_InitSubSystem(0x2000) != 0:
            raise RuntimeError(self.sdl.SDL_GetError().decode(errors="replace"))
        self.handle = None
        self.selected = None
        self.mappings = set()

    def map_device(self, index):
        if (
            self.sdl.SDL_JoystickGetDeviceVendor(index) != 0x057E
            or self.sdl.SDL_JoystickGetDeviceProduct(index) != 0x2069
        ):
            return
        path = self.sdl.SDL_JoystickPathForIndex(index) or b""
        if not path.startswith(b"/dev/input/"):
            return
        guid = c.create_string_buffer(33)
        self.sdl.SDL_JoystickGetGUIDString(self.sdl.SDL_JoystickGetDeviceGUID(index), guid, 33)
        if guid.value not in self.mappings:
            mapping = guid.value + b"," + SWITCH2_MAPPING.encode()
            if self.sdl.SDL_GameControllerAddMapping(mapping) < 0:
                raise RuntimeError(self.sdl.SDL_GetError().decode(errors="replace"))
            self.mappings.add(guid.value)

    def devices(self):
        self.sdl.SDL_PumpEvents()
        result = {}
        for index in range(self.sdl.SDL_NumJoysticks()):
            self.map_device(index)
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
