// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";

export const motionValues = new Map();

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

export function gripSpeed(robot, stop) {
    return motionValue(
        robot,
        stop,
        "grip-speed",
        "Grip speed",
        "gripper speed",
        robot.controls.grip_speed_pct_s,
        1,
        "Percent of gripper travel per second while held",
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

export function inputBlocked() {
    return (
        document.hidden ||
        !document.hasFocus() ||
        !!document.activeElement?.closest(".motion-value") ||
        !!document.querySelector(
            'dialog[open], [role="dialog"][aria-modal="true"]:not([hidden])',
        )
    );
}
