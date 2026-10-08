// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";
import {
    emptyJog,
    inputBlocked,
    jogGroups,
    pairedArms,
} from "./robot-input.js";

const axis = (value) => {
    if (!Number.isFinite(value)) return 0;
    const size = Math.min(1, Math.abs(value));
    return size <= 0.15 ? 0 : (Math.sign(value) * (size - 0.15)) / 0.85;
};

export function gamepadInput(robot, send, stop, stepSize = () => 0.2) {
    const dual = pairedArms(robot);
    const roll = dual && robot.controls.groups.left === 5;
    const container = element("div", undefined, "gamepad-controls");
    const device = document.createElement("select"),
        group = document.createElement("select");
    device.setAttribute("aria-label", `${robot.name} input`);
    device.title =
        "Keyboard or a connected gamepad. Press a gamepad button to detect it.";
    const keyboard = element("option", "Keyboard");
    keyboard.value = "keyboard";
    device.append(keyboard);
    group.setAttribute("aria-label", `${robot.name} gamepad joints`);
    for (const [key, count] of jogGroups(robot)) {
        for (let offset = 0; offset < count; offset += 4) {
            const label = key === "joints" ? "Joints" : `${key} arm · joints`;
            const option = element(
                "option",
                `${label} ${offset + 1}–${Math.min(count, offset + 4)}`,
            );
            option.value = `${key}:${offset}`;
            group.append(option);
        }
    }
    group.hidden = dual || group.options.length < 2;
    const status = element(
        "p",
        "Press a gamepad button to discover it.",
        "gamepad-status",
    );
    const hint = element(
        "p",
        dual
            ? "Hold L1/LB to move. R1/RB selects J3–J4." +
                  (roll ? " L3/R3 + stick up/down rolls each tool." : "") +
                  " Release L1/LB before changing controls."
            : "Hold L1/LB to move. Left stick: first two joints. Right stick: next two. Release to hold.",
        "gamepad-hint",
    );
    const mapping = element("div", undefined, "gamepad-mapping");
    const leftJoints = element("span"),
        rightJoints = element("span");
    mapping.append(
        element("span", "Left stick"),
        leftJoints,
        element("span", "Right stick"),
        rightJoints,
    );
    mapping.hidden = !dual;
    container.append(group, status, mapping, hint);
    let allowed = false,
        enabled = false,
        disposed = false,
        armed = false;
    let signature = "",
        selectedId = "",
        active = false,
        busy = false,
        alternate = false,
        leftRoll = false,
        rightRoll = false,
        lastTick = 0;
    const halt = () => {
        armed = false;
        if (active) {
            active = false;
            stop();
        }
    };
    device.addEventListener("change", () => {
        selectedId = "";
        halt();
    });
    group.onchange = halt;
    function poll() {
        if (disposed) return;
        let pads;
        try {
            pads = Array.from(navigator.getGamepads?.() || []).filter(
                (p) => p?.connected,
            );
        } catch {
            halt();
            status.textContent =
                "Gamepad access is unavailable in this browser.";
            timer = setTimeout(poll, 1000);
            return;
        }
        const next = JSON.stringify(
            pads.map((p) => [p.index, p.id, p.mapping]),
        );
        if (next !== signature) {
            signature = next;
            const selected = device.value;
            device.replaceChildren(keyboard);
            for (const pad of pads) {
                const option = element(
                    "option",
                    pad.id +
                        (pad.mapping === "standard"
                            ? ""
                            : " · unsupported mapping"),
                );
                option.value = String(pad.index);
                option.disabled = pad.mapping !== "standard";
                device.append(option);
            }
            device.value = selected;
            const selectedPad = pads.find((p) => String(p.index) === selected);
            if (
                device.selectedIndex < 0 ||
                (selectedId &&
                    (selectedPad?.id !== selectedId ||
                        selectedPad.mapping !== "standard"))
            ) {
                device.value = "keyboard";
                device.dispatchEvent(new Event("change"));
            }
        }
        const pad = pads.find((p) => String(p.index) === device.value);
        const now = performance.now(),
            delayed = lastTick && now - lastTick > 200;
        lastTick = now;
        const blocked = !enabled || !allowed || inputBlocked();
        if (
            blocked ||
            !pad ||
            pad.mapping !== "standard" ||
            delayed ||
            (selectedId && selectedId !== pad.id)
        ) {
            halt();
            status.textContent = !pad
                ? "Choose a connected gamepad."
                : "Input paused · release LB/L1 to resume.";
        } else {
            selectedId = pad.id;
            const pressed = pad.buttons[4]?.pressed;
            const axes = [
                axis(pad.axes[0]),
                -axis(pad.axes[1]),
                axis(pad.axes[2]),
                -axis(pad.axes[3]),
            ];
            const nextAlternate = dual && Boolean(pad.buttons[5]?.pressed),
                nextLeftRoll = roll && Boolean(pad.buttons[10]?.pressed),
                nextRightRoll = roll && Boolean(pad.buttons[11]?.pressed);
            if (
                nextAlternate !== alternate ||
                nextLeftRoll !== leftRoll ||
                nextRightRoll !== rightRoll
            ) {
                halt();
                alternate = nextAlternate;
                leftRoll = nextLeftRoll;
                rightRoll = nextRightRoll;
            }
            if (!pressed) {
                if (active) {
                    active = false;
                    stop();
                }
                armed = axes.every((v) => v === 0);
                status.textContent = armed
                    ? "Ready · hold LB/L1 to move"
                    : "Center sticks before enabling";
            } else if (armed) {
                status.textContent = "Enabled · joint jog";
                if (axes.some((v) => v !== 0)) {
                    const command = emptyJog(robot);
                    if (dual) {
                        const offset = alternate ? 2 : 0;
                        for (const [arm, start, rolling] of [
                            ["left", 0, leftRoll],
                            ["right", 2, rightRoll],
                        ]) {
                            if (rolling)
                                command[arm][4] = axes[start + 1] * stepSize();
                            else
                                for (let i = 0; i < 2; i++)
                                    command[arm][offset + i] =
                                        axes[start + i] * stepSize();
                        }
                    } else {
                        const [key, start] = group.value.split(":"),
                            offset = Number(start);
                        axes.forEach((v, i) => {
                            if (offset + i < command[key].length)
                                command[key][offset + i] = v * stepSize();
                        });
                    }
                    if (
                        Object.values(command)
                            .flat()
                            .some((v) => v !== 0)
                    ) {
                        if (!busy) {
                            active = true;
                            busy = true;
                            send(command).finally(() => {
                                busy = false;
                            });
                        }
                    }
                } else if (active) {
                    active = false;
                    stop();
                }
            } else
                status.textContent =
                    "Release LB/L1 and center sticks to enable";
        }
        leftJoints.textContent = leftRoll
            ? "Left Roll"
            : alternate
              ? "Left J3 · J4"
              : "Left J1 · J2";
        rightJoints.textContent = rightRoll
            ? "Right Roll"
            : alternate
              ? "Right J3 · J4"
              : "Right J1 · J2";
        if (!disposed) timer = setTimeout(poll, 50);
    }
    let timer = setTimeout(poll, 50);
    return {
        select: device,
        element: container,
        update(on, available) {
            if ((enabled && !on) || (allowed && !available)) halt();
            enabled = on;
            allowed = available;
            container.hidden = !on;
            group.disabled = !available;
        },
        stop: halt,
        destroy() {
            disposed = true;
            clearTimeout(timer);
            halt();
        },
    };
}
