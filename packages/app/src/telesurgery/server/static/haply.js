// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { action, element } from "./ui.js";
import { inputBlocked } from "./robot-input.js";

export const haplyName = "Haply Inverse3";
export const supportsHaply = robot =>
    (robot.kind === "mira-sim" && !!robot.controls?.mira_cartesian) ||
    (["franka-sim", "versius-sim"].includes(robot.kind) && !!robot.controls?.cartesian);

export function haplyInput(robot, send, stop, speeds) {
    const container = element("div", undefined, "gamepad-controls haply-controls");
    const dual = robot.kind === "mira-sim";
    const status = element("p", dual ? "Paused · Left arm" : "Paused", "gamepad-status");
    status.setAttribute("role", "status");
    const arms = element("div", undefined, "motion-section");
    const roll = element("div", undefined, "motion-section");
    const grip = element("div", undefined, "haply-grip-hints");
    const hint = element("p", "", "input-discovery");
    hint.hidden = true;
    for (const text of [
        "Tap single-dot button · Start / stop movement",
        ...(dual ? ["Tap two-dot button · Switch left / right arm"] : []),
        "Move pen · Move tool",
        dual ? "Tilt pen up / down · Angle tool" : "Tilt pen · Angle tool",
    ]) arms.append(element("p", text));
    roll.append(element("p", "Twist pen · Roll tool"));
    for (const text of [
        "Hold single-dot button · Close gripper",
        "Hold two-dot button · Open gripper",
    ]) grip.append(element("p", text));
    container.append(status, arms, roll, hint);
    container.hidden = true;
    let enabled = false, allowed = false, disposed = false, active = false;
    let token = crypto.randomUUID(), busy = false, lastTick = performance.now();
    const halt = () => {
        token = crypto.randomUUID();
        status.textContent = status.textContent.replace(/^Active/, "Paused");
        if (active) {
            active = false;
            Promise.resolve(stop()).catch(() => {});
        }
    };
    const blocked = () => !enabled || !allowed || inputBlocked();
    async function poll() {
        const now = performance.now();
        if (now - lastTick > 200 || (blocked() && active)) halt();
        lastTick = now;
        if (disposed || !enabled || busy) return;
        const issued = now, generation = token, motionEnabled = !blocked();
        busy = true;
        try {
            const result = await action("haply.read", {
                id: robot.id, token: generation, enabled: motionEnabled, speeds: speeds(),
            });
            if (disposed || generation !== token) return;
            if (performance.now() - issued >= 200) { halt(); return; }
            const paused = result.paused || !motionEnabled || blocked();
            status.textContent = `${paused ? "Paused" : "Active"}${dual ? ` · ${result.arm === "right" ? "Right" : "Left"} arm` : ""}`;
            hint.textContent = result.error || "";
            hint.hidden = !result.error;
            // Selecting a device checks readiness without granting robot control.
            if (!motionEnabled || blocked()) { if (active) halt(); return; }
            if (result.request) {
                const [mode, command] = result.request;
                if (mode === "release") {
                    active = false;
                    await stop();
                } else {
                    active = true;
                    await send(mode === "grip" ? {velocity: command} : command, mode);
                }
            }
        } catch (error) {
            if (generation === token) {
                halt();
                hint.textContent = error.message;
                hint.hidden = false;
            }
        } finally { busy = false; }
    }
    const timer = setInterval(poll, 50);
    return {
        element: container, arms, roll, grip,
        update(on, available) {
            if ((enabled && !on) || (allowed && !available)) halt();
            enabled = on;
            allowed = available;
            container.hidden = !on;
        },
        stop: halt,
        destroy() { disposed = true; clearInterval(timer); halt(); },
    };
}
