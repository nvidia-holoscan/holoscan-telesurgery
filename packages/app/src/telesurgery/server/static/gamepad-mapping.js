// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

// Linux joydev exposes Switch 2 Pro HID report 0x09 without a browser mapping.
// Keep this limited to that exact device and layout; other unknown pads stay
// disabled. Standard mappings provided by the browser always take precedence.
export function normalizeGamepad(pad) {
    if (!pad || pad.mapping === "standard" ||
        !/\b057e\b.*\b2069\b/i.test(pad.id) ||
        !/linux/i.test(navigator.platform) ||
        pad.mapping !== "" || pad.axes.length !== 4 || pad.buttons.length !== 21) return pad;
    const buttons = [0, 1, 2, 3, 12, 4, 13, 5, 14, 6, 15, 7, 11, 8, 10, 9, 16];
    return {
        id: pad.id,
        index: pad.index,
        connected: pad.connected,
        timestamp: pad.timestamp,
        mapping: "standard",
        axes: [pad.axes[0], -pad.axes[1], pad.axes[2], -pad.axes[3]],
        buttons: buttons.map(index => pad.buttons[index]),
    };
}
