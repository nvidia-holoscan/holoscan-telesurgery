// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";
import {
    emptyJog,
    inputBlocked,
    jogGroups,
    pairedArms,
} from "./robot-input.js";

const pairs = ["qa", "ws", "ed", "rf", "tg", "yh", "uj"];
const editing = () =>
    document.activeElement?.closest(
        "input, textarea, select, button, a, [contenteditable]:not([contenteditable=false])",
    );

export function keyboardInput(robot, send, stop, stepSize = () => 0.2) {
    const dual = pairedArms(robot);
    const armPairs = {
        left: ["qa", "ws", "ed", "rf", "tg"],
        right: ["uj", "ik", "ol", "p;", "yh"],
    };
    const bindings = new Map();
    const container = element("div", undefined, "keyboard-controls");
    container.tabIndex = 0;
    container.setAttribute("aria-label", `${robot.name} keyboard controls`);
    const group = document.createElement("select");
    group.setAttribute("aria-label", `${robot.name} keyboard joints`);
    for (const [key, count] of jogGroups(robot)) {
        for (let offset = 0; offset < count; offset += pairs.length) {
            const label =
                key === "joints"
                    ? "Joints"
                    : `${key[0].toUpperCase()}${key.slice(1)} arm`;
            const option = element(
                "option",
                count > pairs.length
                    ? `${label} · ${offset + 1}–${Math.min(count, offset + pairs.length)}`
                    : label,
            );
            option.value = `${key}:${offset}`;
            group.append(option);
        }
    }
    group.hidden = dual || group.options.length < 2;
    const status = element("p", undefined, "keyboard-status");
    status.hidden = true;
    status.setAttribute("role", "status");
    const mapping = element("div", undefined, "keyboard-mapping");
    let feedback = robot.state || {};
    let feedbackLabel;
    container.append(group, status, mapping);
    if (!group.hidden)
        container.append(
            element("p", "[ / ] switch joint groups", "gamepad-hint"),
        );
    const keys = new Set();
    const heldKeys = new Set();
    let repeatAt = 0,
        repeating = false;
    let enabled = false,
        allowed = false,
        disposed = false,
        active = false,
        busy = false,
        stopping = false,
        lastTick = 0;

    function pause() {
        if (!active) return;
        active = false;
        stopping = true;
        Promise.resolve(stop()).finally(() => {
            stopping = false;
        });
    }
    function halt() {
        keys.clear();
        heldKeys.clear();
        repeating = false;
        pause();
    }
    function renderMapping() {
        halt();
        const [key, start] = group.value.split(":"),
            offset = Number(start);
        const rows = dual
            ? Object.entries(armPairs).flatMap(([group, keys]) =>
                  keys
                      .slice(0, robot.controls.groups[group])
                      .map((pair, index) => ({
                          group,
                          index,
                          pair,
                      })),
              )
            : pairs
                  .slice(0, robot.controls.groups[key] - offset)
                  .map((pair, i) => ({
                      group: key,
                      index: offset + i,
                      joint: offset + i + 1,
                      pair,
                  }));
        bindings.clear();
        mapping.replaceChildren();
        const heading = element(
            "div",
            undefined,
            "keyboard-joint keyboard-columns",
        );
        if (dual) heading.classList.add("keyboard-paired");
        feedbackLabel = element("span");
        heading.append(
            element("span", "Joint"),
            feedbackLabel,
            element("span", "−"),
            element("span", "+"),
        );
        mapping.append(heading);
        for (const joint of rows) {
            const row = element("div", undefined, "keyboard-joint");
            if (dual) row.classList.add("keyboard-paired");
            if (dual && joint.group === "right" && joint.index === 0)
                row.classList.add("keyboard-arm-divider");
            const value = element("output", "—", "joint-position");
            value.dataset.joint = String(joint.index);
            value.dataset.group = joint.group;
            const name = element(
                "span",
                dual
                    ? `${joint.group === "left" ? "Left" : "Right"} ${joint.index === 4 ? "Roll" : `J${joint.index + 1}`}`
                    : `J${joint.joint}`,
            );
            name.title = dual
                ? `${joint.group} ${joint.index === 4 ? "tool roll" : `arm · joint ${joint.index + 1}`}`
                : "";
            row.append(name, value);
            for (const [key, direction] of [
                [joint.pair[1], "−"],
                [joint.pair[0], "+"],
            ]) {
                bindings.set(key, {
                    group: joint.group,
                    index: joint.index,
                    sign: direction === "+" ? 1 : -1,
                });
                const label = element("span", undefined, "keyboard-binding");
                const cap = element("button", key.toUpperCase(), "key-cap");
                cap.type = "button";
                cap.dataset.key = key;
                cap.setAttribute(
                    "aria-label",
                    `${robot.name} ${joint.group} ${dual && joint.index === 4 ? "roll" : joint.index + 1} ${direction === "+" ? "increase" : "decrease"} (${key.toUpperCase()})`,
                );
                cap.onpointerdown = (event) => {
                    if (event.button !== 0) return;
                    event.preventDefault();
                    container.focus();
                    cap.setPointerCapture(event.pointerId);
                    press(key);
                };
                cap.onpointerup = cap.onlostpointercapture = () => release(key);
                cap.onpointercancel = halt;
                cap.onclick = (event) => {
                    if (event.detail !== 0) return;
                    container.focus();
                    press(key);
                    release(key);
                };
                label.append(cap);
                row.append(label);
            }
            mapping.append(row);
        }
        showFeedback();
    }
    function showFeedback() {
        const joints = feedback.joints_deg || feedback.targets_deg || {};
        feedbackLabel.textContent = feedback.joints_deg
            ? "Measured (°)"
            : "Target (°)";
        feedbackLabel.title =
            feedback.feedback_source || "Simulator drive targets";
        for (const value of mapping.querySelectorAll(".joint-position")) {
            const key = value.dataset.group;
            const position = joints[key]?.[Number(value.dataset.joint)];
            value.textContent = Number.isFinite(position)
                ? position.toFixed(2)
                : "—";
            const velocity =
                    feedback.velocity_deg_s?.[key]?.[
                        Number(value.dataset.joint)
                    ],
                torque =
                    feedback.effort_nm?.[key]?.[Number(value.dataset.joint)],
                target =
                    feedback.targets_deg?.[key]?.[Number(value.dataset.joint)];
            value.title = [
                feedback.joints_deg && Number.isFinite(target)
                    ? `Target ${target.toFixed(2)}°`
                    : "",
                Number.isFinite(velocity)
                    ? `${velocity.toFixed(2)} degrees per second`
                    : "",
                Number.isFinite(torque) ? `${torque.toFixed(2)} Nm` : "",
            ]
                .filter(Boolean)
                .join(" · ");
        }
    }
    group.onchange = () => {
        renderMapping();
        container.focus();
    };
    renderMapping();
    function command(pressed) {
        const value = emptyJog(robot);
        for (const key of pressed) {
            const binding = bindings.get(key);
            if (binding)
                value[binding.group][binding.index] +=
                    binding.sign * stepSize();
        }
        return value;
    }
    function press(key) {
        if (!enabled || !allowed || inputBlocked() || keys.has(key)) return;
        keys.add(key);
        if (stopping || (heldKeys.size && !dual)) return;
        // Track both hands while held; never queue a released tap behind a request.
        if (busy && !(dual && heldKeys.size)) return;
        if (!heldKeys.size) {
            repeating = false;
            repeatAt = performance.now() + 450;
        }
        heldKeys.add(key);
        if (!busy) issue([key]);
    }
    function release(key) {
        keys.delete(key);
        heldKeys.delete(key);
        if (!heldKeys.size) {
            if (repeating) pause();
            repeating = false;
        }
    }
    function issue(pressed, continuous = false) {
        if (busy || stopping) return;
        const value = command(pressed);
        if (
            !Object.values(value)
                .flat()
                .some((v) => v !== 0)
        )
            return;
        active = busy = true;
        Promise.resolve(send(value, continuous))
            .catch(halt)
            .finally(() => {
                busy = false;
            });
    }
    function keydown(event) {
        if (
            !enabled ||
            !allowed ||
            inputBlocked() ||
            editing() ||
            event.isComposing ||
            event.ctrlKey ||
            event.altKey ||
            event.metaKey
        ) {
            halt();
            return;
        }
        const key = event.key.toLowerCase();
        if (!["escape", "[", "]"].includes(key) && !bindings.has(key)) return;
        event.preventDefault();
        if (event.repeat || keys.has(key)) return;
        if (key === "escape") {
            halt();
            return;
        }
        if (key === "[" || key === "]") {
            if (group.hidden) return;
            group.selectedIndex =
                (group.selectedIndex +
                    (key === "[" ? -1 : 1) +
                    group.options.length) %
                group.options.length;
            renderMapping();
            return;
        }
        press(key);
    }
    function keyup(event) {
        const key = event.key.toLowerCase();
        release(key);
    }
    function poll() {
        if (disposed) return;
        const now = performance.now(),
            delayed = lastTick && now - lastTick > 200;
        lastTick = now;
        if (!enabled || !allowed || inputBlocked() || editing() || delayed)
            halt();
        if (heldKeys.size && now >= repeatAt && !busy && !stopping) {
            repeating = true;
            repeatAt = now + 50;
            issue(heldKeys, true);
        }
        status.textContent = feedback.stopping
            ? "Stopping · Release keys"
            : feedback.home_active
              ? "Going home · Esc to stop"
              : !allowed
                ? "Keyboard unavailable"
                : "";
        status.hidden = !status.textContent;
        for (const cap of mapping.querySelectorAll(".key-cap")) {
            cap.dataset.pressed = String(keys.has(cap.dataset.key));
            cap.disabled = !enabled || !allowed;
        }
        timer = setTimeout(poll, 50);
    }
    window.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);
    window.addEventListener("blur", halt);
    document.addEventListener("visibilitychange", halt);
    let timer = setTimeout(poll, 50);
    return {
        element: container,
        update(on, available) {
            if ((enabled && !on) || (allowed && !available)) halt();
            if (on && !enabled) {
                halt();
                lastTick = performance.now();
                container.hidden = false;
                container.focus();
            }
            enabled = on;
            allowed = available;
            container.hidden = !on;
            group.disabled = !available;
        },
        feedback(state) {
            feedback = state || {};
            showFeedback();
        },
        stop: halt,
        destroy() {
            disposed = true;
            clearTimeout(timer);
            window.removeEventListener("keydown", keydown);
            window.removeEventListener("keyup", keyup);
            window.removeEventListener("blur", halt);
            document.removeEventListener("visibilitychange", halt);
            halt();
        },
    };
}
