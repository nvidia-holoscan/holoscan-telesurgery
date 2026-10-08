// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";
import { inputBlocked } from "./robot-input.js";

const editing = () => document.activeElement?.closest(
    "input, textarea, select, button, a, [contenteditable]:not([contenteditable=false])",
);

export function gripperControls(robot, send, stop, speed) {
    const panel = element("div", undefined, "gripper-controls");
    panel.tabIndex = 0;
    panel.setAttribute("aria-label", `${robot.name} gripper controls`);
    panel.title = "Hold to open or close · Release to stop";
    const bindings = new Map(), pressed = new Set(), buttons = new Map();
    let allowed = false, keyboard = false, busy = false, active = false,
        stopping = false, previous = performance.now();
    function halt() {
        pressed.clear();
        if (!active) return;
        active = false;
        stopping = true;
        Promise.resolve(stop()).finally(() => { stopping = false; });
    }
    function issue() {
        if (busy || stopping || !pressed.size) return;
        const velocity = Object.fromEntries(robot.controls.grippers.map(arm => [arm, 0]));
        for (const key of pressed) {
            const { arm, sign } = bindings.get(key);
            velocity[arm] += sign * speed() / 100;
        }
        active = busy = true;
        Promise.resolve(send({ velocity })).catch(halt).finally(() => { busy = false; });
    }
    function press(key) {
        if (!allowed || inputBlocked() || stopping || pressed.has(key)) return;
        pressed.add(key);
        issue();
    }
    function release(key) {
        if (!pressed.delete(key)) return;
        if (pressed.size) issue();
        else halt();
    }
    for (const arm of robot.controls.grippers) {
        const row = element("div", undefined, "gripper-control");
        row.append(element("span", `${arm[0].toUpperCase() + arm.slice(1)} grip`));
        const keys = arm === "left" ? "zx" : "nm";
        for (const [index, label, sign] of [[0, "Close", -1], [1, "Open", 1]]) {
            const key = keys[index], control = element("button", undefined, "secondary small");
            control.type = "button";
            control.append(element("kbd", key.toUpperCase()), document.createTextNode(` ${label}`));
            control.setAttribute("aria-label", `${label} ${arm} gripper`);
            control.title = `Hold ${key.toUpperCase()} or this button to ${label.toLowerCase()}`;
            bindings.set(key, { arm, sign });
            buttons.set(key, control);
            control.onpointerdown = event => {
                if (event.button !== 0) return;
                event.preventDefault();
                panel.focus();
                control.setPointerCapture(event.pointerId);
                press(key);
            };
            control.onpointerup = control.onlostpointercapture = () => release(key);
            control.onpointercancel = halt;
            control.onkeydown = event => {
                if (![" ", "Enter"].includes(event.key)) return;
                event.preventDefault();
                if (!event.repeat) press(key);
            };
            control.onkeyup = event => {
                if ([" ", "Enter"].includes(event.key)) release(key);
            };
            row.append(control);
        }
        panel.append(row);
    }
    function keydown(event) {
        const key = event.key.toLowerCase();
        if (key === "escape") { halt(); return; }
        if (!keyboard || !bindings.has(key)) return;
        if (editing() || event.isComposing || event.ctrlKey || event.altKey || event.metaKey) {
            halt();
            return;
        }
        event.preventDefault();
        if (!event.repeat) press(key);
    }
    const keyup = event => release(event.key.toLowerCase());
    window.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);
    window.addEventListener("blur", halt);
    document.addEventListener("visibilitychange", halt);
    const timer = setInterval(() => {
        const now = performance.now();
        if (!allowed || inputBlocked() || now - previous > 200) halt();
        previous = now;
        if (pressed.size) issue();
        for (const [key, control] of buttons) {
            control.disabled = !allowed;
            control.dataset.pressed = String(pressed.has(key));
        }
    }, 50);
    return {
        element: panel,
        update(enabled, keyboardEnabled) {
            if ((allowed && !enabled) || keyboard !== keyboardEnabled) halt();
            allowed = enabled;
            keyboard = keyboardEnabled;
            for (const control of buttons.values()) control.disabled = !allowed;
        },
        stop: halt,
        destroy() {
            halt();
            clearInterval(timer);
            window.removeEventListener("keydown", keydown);
            window.removeEventListener("keyup", keyup);
            window.removeEventListener("blur", halt);
            document.removeEventListener("visibilitychange", halt);
        },
    };
}
