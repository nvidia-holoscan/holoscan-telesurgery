// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";
import { icon } from "./icons.js";
import { inputBlocked, keyboardHolds } from "./robot-input.js";

const editing = () => document.activeElement?.closest(
    "input, textarea, select, button, a, [contenteditable]:not([contenteditable=false])",
);

export function gripperControls(robot, send, stop, speed) {
    const panel = element("div", undefined, "gripper-controls");
    panel.tabIndex = 0;
    panel.setAttribute("aria-label", `${robot.name} gripper controls`);
    panel.title = "Hold to open or close · Release to stop";
    const heading = element("div", undefined, "gripper-heading");
    heading.append(element("strong", "Grippers"));
    panel.append(heading);
    const single = robot.controls.grippers.length === 1 && robot.controls.grippers[0] === "hand";
    if (single) panel.classList.add("single-gripper");
    const toggle = element("div", undefined, "gamepad-instructions grip-toggle");
    const toggleKey = element("kbd");
    toggle.append(toggleKey, element("span", "Open / close"));
    toggle.hidden = true;
    if (single) panel.append(toggle);
    const bindings = new Map(), pressed = new Set(), buttons = new Map(), readings = new Map();
    const physicalKeys = keyboardHolds(release);
    let gamepadVelocity = {};
    let allowed = false, keyboard = false, busy = false, active = false,
        stopping = false, previous = performance.now();
    function halt() {
        pressed.clear();
        gamepadVelocity = {};
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
        buttons.get(key).dataset.pressed = "false";
        if (pressed.size) issue();
        else halt();
    }
    for (const arm of robot.controls.grippers) {
        const row = element("div", undefined, "gripper-control");
        if (!single) row.append(element("span", arm[0].toUpperCase() + arm.slice(1)));
        const keys = arm === "left" || arm === "hand" ? "zx" : "nm";
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
                if (physicalKeys.press(key, event.repeat)) press(key);
            };
            control.onkeyup = event => {
                if ([" ", "Enter"].includes(event.key)) physicalKeys.release(key);
            };
            row.append(control);
        }
        const feedback = element("div", undefined, "gripper-feedback");
        const opening = document.createElement("meter");
        opening.min = 0;
        opening.max = 1;
        opening.setAttribute("aria-label", `${arm} gripper opening`);
        const value = element("output", "—");
        value.setAttribute("aria-label", `${arm} gripper measured opening`);
        feedback.title = "Measured opening · 0% closed · 100% open";
        feedback.append(opening, value);
        row.append(feedback);
        readings.set(arm, {opening, value});
        panel.append(row);
    }
    function feedback(state) {
        for (const [arm, {opening, value}] of readings) {
            const measured = state?.grippers?.[arm];
            const known = Number.isFinite(measured);
            opening.hidden = !known;
            if (known) opening.value = Math.max(0, Math.min(1, measured));
            const percent = Math.round(opening.value * 100);
            opening.setAttribute("aria-valuetext", known ? `${percent}% open` : "Unknown");
            value.textContent = known ? `${percent}%` : "—";
        }
    }
    feedback(robot.state);
    function keydown(event) {
        const key = event.key.toLowerCase();
        if (key === "escape") { halt(); return; }
        if (!bindings.has(key)) return;
        const fresh = physicalKeys.press(key, event.repeat);
        if (!keyboard) return;
        if (editing() || event.isComposing || event.ctrlKey || event.altKey || event.metaKey) {
            halt();
            return;
        }
        event.preventDefault();
        if (fresh) press(key);
    }
    const keyup = event => physicalKeys.release(event.key.toLowerCase());
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
            const {arm, sign} = bindings.get(key);
            control.disabled = !allowed;
            control.dataset.pressed = String(pressed.has(key) ||
                (allowed && !keyboard && Math.sign(gamepadVelocity[arm] || 0) === sign));
        }
    }, 50);
    return {
        element: panel,
        feedback,
        gamepad(velocity) { gamepadVelocity = velocity; },
        update(enabled, keyboardEnabled, gamepad) {
            if ((allowed && !enabled) || keyboard !== keyboardEnabled) halt();
            allowed = enabled;
            keyboard = keyboardEnabled;
            heading.hidden = !!panel.querySelector(".speed-control");
            toggle.hidden = !single || keyboard;
            if (single) {
                toggleKey.textContent = gamepad?.n || "□";
                toggle.title = `Press ${gamepad?.n || "□"} to toggle the gripper · Stop / Esc interrupts motion`;
            }
            for (const [key, control] of buttons) {
                control.disabled = !allowed;
                const cap = control.querySelector("kbd");
                cap.hidden = single && !keyboard;
                const label = keyboard ? key.toUpperCase() : gamepad?.[key] || "";
                if (cap.dataset.binding !== label) {
                    cap.dataset.binding = label;
                    const symbol = {"←": "left", "→": "right", "□": "square", "○": "circle"}[label];
                    if (symbol) cap.replaceChildren(icon(symbol), element("span", label, "sr-only"));
                    else cap.textContent = label;
                }
                control.title = keyboard
                    ? `Hold ${key.toUpperCase()} or this button to ${bindings.get(key).sign < 0 ? "close" : "open"}`
                    : single ? "Hold this button · Release to stop"
                    : `Hold ${gamepad?.enable || "LB/L1"} + ${gamepad?.[key] || "gamepad button"}, or hold this on-screen button`;
            }
        },
        stop: halt,
        destroy() {
            halt();
            physicalKeys.destroy();
            clearInterval(timer);
            window.removeEventListener("keydown", keydown);
            window.removeEventListener("keyup", keyup);
            window.removeEventListener("blur", halt);
            document.removeEventListener("visibilitychange", halt);
        },
    };
}
