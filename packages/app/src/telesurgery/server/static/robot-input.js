// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";

export const motionValues = new Map();

export function keyboardHolds(release) {
    // Keep physical holds across input halts, so repeat pairs cannot rearm motion.
    const down = new Set(), pending = new Map();
    return {
        press(key, repeat) {
            clearTimeout(pending.get(key));
            pending.delete(key);
            const fresh = !down.has(key) && !repeat;
            down.add(key);
            return fresh;
        },
        release(key) {
            if (!down.has(key)) return;
            clearTimeout(pending.get(key));
            // Some Linux keyboard paths report autorepeat as keyup/keydown
            // pairs (repeat=false), observed up to 9 ms apart on the host.
            // Coalesce those pairs; a real release stops within 20 ms. Focus
            // loss, Escape and the input watchdog still stop immediately.
            pending.set(key, setTimeout(() => {
                pending.delete(key);
                down.delete(key);
                release(key);
            }, 20));
        },
        destroy() {
            for (const timer of pending.values()) clearTimeout(timer);
            pending.clear();
            down.clear();
        },
    };
}

export function jointStep(robot, stop) {
    const maximum =
        robot.controls.max_step_deg || robot.controls.step_deg || 0.2;
    return motionValue(
        robot,
        stop,
        "step",
        "Step (°)",
        "joint step",
        {
            min: Math.min(0.05, maximum),
            max: maximum,
            default: robot.controls.default_step_deg || 0.2,
        },
        0.01,
        "Distance per key press or full stick deflection",
    );
}

export function jointSpeed(robot, stop) {
    return motionValue(
        robot,
        stop,
        "speed",
        "Speed",
        "joint speed",
        robot.controls.speed_deg_s,
        0.1,
        "Maximum joint speed in degrees per second for jogs and Home; short moves may be slower",
    );
}

function motionValue(
    robot,
    stop,
    kind,
    title,
    accessible,
    limits,
    increment,
    hint,
) {
    const key = `${robot.id}:${kind}`;
    let value = Math.max(
        limits.min,
        Math.min(motionValues.get(key) ?? limits.default, limits.max),
    );
    const container = element("div", undefined, "motion-value");
    const label = element("label", title);
    const number = document.createElement("input");
    number.type = "number";
    number.id = `joint-${kind}-${robot.id}`;
    number.setAttribute("aria-label", `${robot.name} ${accessible}`);
    label.htmlFor = number.id;
    container.title = `${hint} · ${limits.min}–${limits.max}`;
    number.min = String(limits.min);
    number.max = String(limits.max);
    number.step = String(increment);
    number.value = String(value);
    number.oninput = () => {
        stop();
        if (!number.checkValidity() || !Number.isFinite(number.valueAsNumber))
            return;
        value = number.valueAsNumber;
        motionValues.set(key, value);
    };
    number.onblur = () => {
        number.value = String(value);
    };
    container.onfocusin = stop;
    number.onkeydown = (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            number.blur();
        }
    };
    container.append(label, number);
    return {
        element: container,
        value: () => value,
        update(available) {
            number.disabled = !available;
        },
    };
}

export function armSpeed(robot, stop) {
    const maximum = robot.controls.max_step_deg || robot.controls.step_deg || 0.2;
    const limits = robot.controls.speed_deg_s || {
        min: 0,
        max: robot.controls.joint_velocity?.arm_deg_s ?? maximum * 20,
        default: (robot.controls.default_step_deg || 0.2) * 20,
    };
    return motionSpeed(robot, stop, "arm-speed", "Arm speed", limits,
        robot.controls.default_arm_speed_percent ?? 20, maximum);
}

export function rollSpeed(robot, stop) {
    const maximum = robot.controls.max_step_deg || robot.controls.step_deg || 0.2;
    return motionSpeed(robot, stop, "roll-speed", "Rotation speed", {
        min: 0,
        max: robot.controls.joint_velocity?.roll_deg_s ?? robot.controls.cartesian?.angular_speed_deg_s ?? maximum * 20,
        default: (robot.controls.default_step_deg || 0.2) * 20,
    }, robot.controls.default_roll_speed_percent ?? 50, maximum);
}

export function gripSpeed(robot, stop) {
    return motionSpeed(robot, stop, "grip-speed", "Grip speed", robot.controls.grip_speed_pct_s,
        robot.controls.default_grip_speed_percent ?? 40);
}

function motionSpeed(robot, stop, kind, title, limits, defaultPercent, maximumStep) {
    const key = `${robot.id}:${kind}`;
    const minimum = Math.max(1, Math.ceil(limits.min / limits.max * 100));
    let percent = Math.max(minimum, Math.min(100,
        motionValues.get(key) ?? defaultPercent));
    const container = element("div", undefined, "motion-value speed-control");
    container.title = "Percentage of this robot’s configured speed limit. Acceleration, contact and joint limits can reduce actual speed.";
    const label = element("label", title);
    const slider = document.createElement("input");
    const output = element("output");
    slider.type = "range";
    slider.id = `speed-${kind}-${robot.id}`;
    slider.setAttribute("aria-label", `${robot.name} ${title.toLowerCase()}`);
    label.htmlFor = slider.id;
    output.htmlFor = slider.id;
    slider.min = String(minimum);
    slider.max = "100";
    slider.step = "1";
    slider.title = "Slow to fast";
    function show() {
        slider.value = String(percent);
        output.textContent = `${percent}%`;
        slider.style.setProperty("--speed-fill", `${(percent - minimum) / Math.max(1, 100 - minimum) * 100}%`);
        slider.setAttribute("aria-valuetext", `${percent}% speed`);
    }
    show();
    slider.oninput = () => {
        stop();
        if (!Number.isFinite(slider.valueAsNumber)) return;
        percent = Math.max(minimum, Math.min(100, Math.round(slider.valueAsNumber)));
        motionValues.set(key, percent);
        show();
    };
    container.onfocusin = stop;
    slider.onpointerup = () => slider.blur();
    slider.onkeydown = event => {
        if (event.key === "Enter") {
            event.preventDefault();
            slider.blur();
        }
    };
    container.append(label, slider, output);
    const value = () => Math.max(limits.min, limits.max * percent / 100);
    return {
        element: container,
        value,
        percent: () => percent,
        increment: (seconds = 0.05) => Math.min(maximumStep, value() * seconds),
        update(available) { slider.disabled = !available; },
    };
}

export function jogGroups(robot) {
    return Object.entries(robot.controls?.groups || {});
}

export function pairedArms(robot) {
    return (
        jogGroups(robot).length === 2 &&
        [4, 5].includes(robot.controls.groups.left) &&
        robot.controls.groups.right === robot.controls.groups.left
    );
}

export function emptyJog(robot) {
    return Object.fromEntries(
        jogGroups(robot).map(([key, count]) => [key, Array(count).fill(0)]),
    );
}

export function inputBlocked({allowUnfocused = false} = {}) {
    return (
        document.hidden ||
        (!allowUnfocused && !document.hasFocus()) ||
        !!document.activeElement?.closest(".motion-value") ||
        !!document.querySelector(
            'dialog[open], [role="dialog"][aria-modal="true"]:not([hidden])',
        )
    );
}

// Convert the speed-scaled joint input into the bounded MIRA tool-jog contract.
export function miraToolJog(robot, command) {
    const config = robot.controls.mira_cartesian;
    const maximum = robot.controls.max_step_deg || 1;
    return Object.fromEntries(Object.entries(command).map(([arm, values]) => {
        const rates = robot.controls.joint_velocity;
        const result = values.map((v, i) => v / (rates ? (i === 4 ? rates.roll_deg_s : rates.arm_deg_s) / 20 : maximum) *
            (i < 3 ? config.linear_step_mm : i === 4 ?
                (config.roll_step_deg ?? config.angular_step_deg) : config.angular_step_deg));
        const length = Math.hypot(...result.slice(0, 3));
        if (length > config.linear_step_mm)
            for (let i = 0; i < 3; i++) result[i] *= config.linear_step_mm / length;
        for (const i of [3, 4]) {
            const limit = i === 4 ? (config.roll_step_deg ?? config.angular_step_deg) : config.angular_step_deg;
            result[i] = Math.max(-limit, Math.min(limit, result[i]));
        }
        return [arm, result];
    }));
}
