# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Describe controller bindings for an actual checkpoint correction, for display only."""

import math

from telesurgery.controller.input import ARM_PAIRS, GRIP_KEYS, PAIRS, TOOL_KEYS


def command_input(inputs, device, request, previous_mode=None):
    if device not in {"keyboard", "gamepad"}:
        return None
    operation, command = request
    if operation == "grip":
        mode = previous_mode or inputs.mode
    elif operation == "cartesian":
        mode = "mira-tool"
    else:
        mode = "cartesian" if "translation" in command else "joints"
    keys, buttons = [], set()
    axes, banks = [0.0] * 4, [[0.0] * 4, [0.0] * 4]
    grip = command if operation == "grip" else {}

    def stick(value):
        # Display uses standard gamepad samples (before deadzone and Y inversion).
        return math.copysign(0.15 + 0.85 * min(1, abs(value)), value) if value else 0.0

    for group, rate in grip.items():
        if not rate:
            continue
        keys.append(GRIP_KEYS[group][int(rate > 0)])
        close, opened = (14, 15) if group == "left" else (2, 1)
        # Franka's tool-mode gamepad uses one toggle for both directions.
        buttons.add(
            2
            if group == "hand" and mode == "cartesian" and not inputs.hold_grip
            else opened
            if rate > 0
            else close
        )
    if operation != "grip":
        if mode == "cartesian":
            for key, (group, index, sign) in TOOL_KEYS.items():
                if command[group][index] * sign > 0:
                    keys.append(key)
            x, y, z = command["translation"]
            rx, ry, rz = command["rotation"]
            axes = [stick(v) for v in (-y, -x, -rz, -z)]
            if rx:
                buttons.add(14 if rx > 0 else 15)
            if ry:
                buttons.add(13 if ry > 0 else 12)
        else:
            scale = max((abs(v) for values in command.values() for v in values), default=1) or 1
            for group, values in command.items():
                pairs = ARM_PAIRS[group] if inputs.dual else PAIRS
                for index, value in enumerate(values):
                    if not value:
                        continue
                    keys.append(pairs[index][int(value < 0)])
                    if inputs.dual and index == 4:
                        positive, negative = (12, 13) if group == "left" else (3, 0)
                        buttons.add(positive if value > 0 else negative)
                        continue
                    bank, axis = divmod(index, 2 if inputs.dual else 4)
                    if inputs.dual and group == "right":
                        axis += 2
                    banks[bank][axis] = stick(value / scale * (-1 if axis % 2 else 1))
            # Checkpoints can correct both banks together. Keep them separate in
            # the display instead of inventing a single impossible stick sample.
            axes = next((bank[:] for bank in banks if any(bank)), axes)
    if mode != "cartesian" and (keys or buttons):
        buttons.add(4)
        if any(banks[1]):
            buttons.add(5)
    return {
        "device": device,
        "mode": mode,
        "keys": keys,
        "axes": axes,
        "buttons": sorted(buttons),
        "banks": banks,
        "grip": dict(grip),
    }
