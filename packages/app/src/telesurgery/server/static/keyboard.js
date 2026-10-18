// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";
import {
    emptyJog,
    inputBlocked,
    jogGroups,
    pairedArms,
    miraToolJog,
    keyboardHolds,
} from "./robot-input.js";

const pairs = ["qa", "ws", "ed", "rf", "tg", "yh", "uj", "ik"];
const editing = () =>
    document.activeElement?.closest(
        "input, textarea, select, button, a, [contenteditable]:not([contenteditable=false])",
    );

export function keyboardInput(robot, send, stop, stepSize = () => 0.2, jointSpeed = null) {
    const dual = pairedArms(robot);
    const armPairs = {
        left: ["qa", "ws", "ed", "rf", "tg"],
        right: ["uj", "ik", "ol", "p;", "yh"],
    };
    const bindings = new Map();
    const container = element("div", undefined, "keyboard-controls");
    const inputStatus = element("p", "", "robot-input-status");
    inputStatus.setAttribute("role", "status");
    container.tabIndex = 0;
    container.setAttribute("aria-label", `${robot.name} keyboard controls`);
    const group = document.createElement("select");
    group.setAttribute("aria-label", `${robot.name} keyboard joints`);
    const toolControl = Boolean(robot.controls.cartesian);
    const miraTool = Boolean(robot.controls.mira_cartesian);
    if (toolControl) {
        group.setAttribute("aria-label", `${robot.name} keyboard mode`);
        const option = element("option", "Tool movement");
        option.value = "cartesian";
        group.append(option);
    }
    const cartesian = () => toolControl && group.value === "cartesian";
    for (const [key, count] of jogGroups(robot)) {
        for (let offset = 0; offset < count; offset += pairs.length) {
            const label =
                key === "joints"
                    ? toolControl ? "Individual joints (advanced)" : "Joints"
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
    if (miraTool) {
        group.replaceChildren();
        group.setAttribute("aria-label", `${robot.name} keyboard mode`);
        for (const [value, label] of [["joints", "Joint movement"], ["mira-tool", "Tool movement · X/Y/Z + elbow"]]) {
            const option = element("option", label);
            option.value = value;
            group.append(option);
        }
    }
    const miraCartesian = () => miraTool && group.value === "mira-tool";
    const jointVelocity = () => Boolean(jointSpeed && robot.controls.joint_velocity && !cartesian() && !miraCartesian());
    const continuousTool = () => cartesian() || miraCartesian() || jointVelocity();
    group.hidden = (dual && !miraTool) || group.options.length < 2;
    const mapping = element("div", undefined, "keyboard-mapping");
    const arms = element("div", undefined, "motion-section");
    const rollControls = element("div", undefined, "motion-section");
    const armRows = element("div", undefined, "keyboard-rows");
    const rollRows = element("div", undefined, "keyboard-rows");
    if (dual) {
        armRows.classList.add("keyboard-arms");
        rollRows.classList.add("keyboard-arms");
    }
    arms.append(armRows);
    rollControls.append(rollRows);
    rollControls.hidden = !dual || robot.controls.groups.left !== 5;
    mapping.append(arms, rollControls);
    let feedback = robot.state || {};
    let feedbackLabels = [];
    container.append(group, inputStatus, mapping);
    if (!group.hidden && !toolControl && !miraTool)
        container.append(
            element("p", "[ / ] switch joint groups", "gamepad-hint"),
        );
    const keys = new Set();
    const heldKeys = new Set();
    const physicalKeys = keyboardHolds(release);
    let repeatAt = 0,
        repeating = false,
        lastJogAt = 0;
    let enabled = false,
        allowed = false,
        disposed = false,
        active = false,
        busy = false,
        stopping = false,
        lastSentAt = -Infinity,
        lastTick = 0;

    function pause() {
        if (!active) return;
        active = false;
        stopping = true;
        showInputStatus();
        Promise.resolve(stop()).finally(() => {
            stopping = false;
            showInputStatus();
        });
    }
    function showInputStatus(ignored = false) {
        const reason = stopping || feedback.stopping ? "Stopping…" : feedback.home_active ? "Going Home…" : "";
        inputStatus.textContent = reason
            ? `${reason} ${ignored ? "Input ignored. " : ""}Release, then retry.`
            : continuousTool() ? "Hold to move · Release to stop" : "Press a key or button to step";
        inputStatus.title = inputStatus.textContent;
    }
    function halt() {
        lastJogAt = 0;
        keys.clear();
        heldKeys.clear();
        repeating = false;
        pause();
    }
    function renderMapping() {
        halt();
        rollControls.hidden = !((dual && robot.controls.groups.left === 5) ||
            (cartesian() && robot.controls.cartesian.independent_rotation));
        armRows.classList.toggle("cartesian-keyboard", cartesian());
        if (cartesian()) {
            bindings.clear();
            armRows.replaceChildren();
            rollRows.replaceChildren();
            feedbackLabels = [];
            for (const [title, rows] of [
                ["Move", [
                    ["Forward / back", "translation", 0, [["w", "W", 1, "Forward"], ["s", "S", -1, "Back"]]],
                    ["Left / right", "translation", 1, [["a", "A", 1, "Left"], ["d", "D", -1, "Right"]]],
                    ["Up / down", "translation", 2, [["r", "R", 1, "Up"], ["f", "F", -1, "Down"]]],
                ]],
                ["Rotate", [
                    ["Turn", "rotation", 2, [["q", "Q", 1, "Turn left"], ["e", "E", -1, "Turn right"]]],
                    ["Side tilt", "rotation", 0, [["arrowleft", "←", 1, "Tilt left"], ["arrowright", "→", -1, "Tilt right"]]],
                    ["Forward tilt", "rotation", 1, [["arrowup", "↑", -1, "Tilt forward"], ["arrowdown", "↓", 1, "Tilt back"]]],
                ]],
            ]) {
                const section = element("div");
                section.append(element("span", title, "cartesian-label"));
                for (const [label, group, index, keys] of rows) {
                    const row = element("div", undefined, "cartesian-keyboard-row");
                    for (const [key, symbol, sign, direction] of keys) {
                        bindings.set(key, {group, index, sign});
                        row.append(keyButton(key, symbol, `${robot.name} ${direction} (${symbol})`));
                    }
                    row.append(element("span", label));
                    section.append(row);
                }
                armRows.append(section);
            }
            const hint = element("div", undefined, "cartesian-keyboard-hint");
            const frame = element("span", "Arm-base directions");
            frame.title = "Relative to this arm’s fixed base: forward +X, left +Y, up +Z. Camera and tool rotation do not change these directions.";
            hint.append(frame);
            armRows.append(hint);
            return;
        }
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
        armRows.replaceChildren();
        rollRows.replaceChildren();
        feedbackLabels = [];
        const sections = new Map();
        for (const section of [armRows, ...(!rollControls.hidden ? [rollRows] : [])]) {
            for (const arm of dual ? ["left", "right"] : [key]) {
                const block = element("div", undefined, "keyboard-rows");
                sections.set(`${section === rollRows ? "roll" : "arm"}:${arm}`, block);
                const heading = element("div", undefined, "keyboard-joint keyboard-columns");
                if (dual) heading.classList.add("keyboard-paired");
                const feedbackLabel = element("span");
                feedbackLabels.push(feedbackLabel);
                heading.append(
                    element("span", dual ? (arm === "left" ? "Left" : "Right") : "Joint"),
                    feedbackLabel, element("span", "−"), element("span", "+"),
                );
                block.append(heading);
                section.append(block);
            }
        }
        for (const joint of rows) {
            const row = element("div", undefined, "keyboard-joint");
            if (dual) row.classList.add("keyboard-paired");
            const value = element("output", "—", "joint-position");
            value.dataset.joint = String(joint.index);
            value.dataset.group = joint.group;
            const name = element(
                "span",
                dual
                    ? (miraCartesian() ? robot.controls.mira_cartesian.axes[joint.index] : joint.index === 4 ? "" : `J${joint.index + 1}`)
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
                row.append(keyButton(key, key.toUpperCase(),
                    `${robot.name} ${joint.group} ${dual && joint.index === 4 ? "roll" : joint.index + 1} ${direction === "+" ? "increase" : "decrease"} (${key.toUpperCase()})`,
                ));
            }
            sections.get(`${dual && joint.index === 4 ? "roll" : "arm"}:${joint.group}`).append(row);
        }
        showFeedback();
    }
    function keyButton(key, symbol, description) {
        const label = element("span", undefined, "keyboard-binding");
        const cap = element("button", symbol, "key-cap");
        cap.type = "button";
        cap.disabled = true;
        cap.dataset.key = key;
        cap.setAttribute("aria-label", description);
        cap.title = description;
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
        return label;
    }
    function showFeedback() {
        const joints = feedback.joints_deg || feedback.targets_deg || {};
        for (const feedbackLabel of feedbackLabels) {
            feedbackLabel.textContent = miraCartesian() ? "mm / °" : dual ? "°" : feedback.joints_deg ? "Measured (°)" : "Target (°)";
            feedbackLabel.title = `${feedback.joints_deg ? "Measured" : "Target"} · ${feedback.feedback_source || "Simulator drive targets"}`;
        }
        for (const value of mapping.querySelectorAll(".joint-position")) {
            const key = value.dataset.group;
            const index = Number(value.dataset.joint);
            const position = miraCartesian() && index < 4
                ? feedback.cartesian_mm_deg?.[key]?.[index] : joints[key]?.[index];
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
    function command(pressed, seconds) {
        const value = cartesian() ? {translation: [0, 0, 0], rotation: [0, 0, 0]} : emptyJog(robot);
        for (const key of pressed) {
            const binding = bindings.get(key);
            if (binding)
                value[binding.group][binding.index] +=
                    binding.sign * (cartesian() ? 1 : jointVelocity() ? jointSpeed(binding.group, binding.index) : stepSize(binding.group, binding.index, seconds));
        }
        return miraCartesian() ? miraToolJog(robot, value) : value;
    }
    function press(key) {
        if (stopping || feedback.stopping || feedback.home_active) {
            showInputStatus(true);
            return;
        }
        if (!enabled || !allowed || inputBlocked() || keys.has(key)) return;
        if (stopping || (heldKeys.size && !dual && !continuousTool())) return;
        keys.add(key);
        // Track both hands while held; never queue a released tap behind a request.
        if (busy && !continuousTool() && !(dual && heldKeys.size)) return;
        if (!heldKeys.size) {
            lastJogAt = 0;
            repeating = false;
            repeatAt = performance.now() + (continuousTool() ? 0 : 450);
        }
        heldKeys.add(key);
        if (!busy) issue(continuousTool() ? heldKeys : [key], continuousTool());
    }
    function release(key) {
        keys.delete(key);
        heldKeys.delete(key);
        const cap = mapping.querySelector(`.key-cap[data-key="${key}"]`);
        if (cap) cap.dataset.pressed = "false";
        if (!heldKeys.size) {
            if (repeating || continuousTool()) pause();
            repeating = false;
        }
    }
    function issue(pressed, continuous = false) {
        if (busy || stopping) return;
        const now = performance.now();
        if (continuousTool() && now - lastSentAt < 50) return;
        const seconds = continuous && lastJogAt ? Math.min(0.1, (now - lastJogAt) / 1000) : 0.05;
        const value = command(pressed, seconds);
        if (
            !Object.values(value)
                .flat()
                .some((v) => v !== 0)
        ) {
            if (continuousTool()) pause();
            return;
        }
        active = busy = true;
        lastSentAt = now;
        lastJogAt = continuous ? now : 0;
        Promise.resolve(send(value, continuous, miraCartesian() ? "cartesian" : jointVelocity() ? "velocity" : undefined))
            .catch(halt)
            .finally(() => {
                busy = false;
                // Resample held keys immediately after a slow response; never
                // queue old directions or add another 50 ms to its latency.
                if (continuousTool() && !disposed) {
                    clearTimeout(timer);
                    timer = setTimeout(poll, Math.max(0, 50 - (performance.now() - lastSentAt)));
                }
            });
    }
    function keydown(event) {
        const key = event.key.toLowerCase();
        const fresh = bindings.has(key) ? physicalKeys.press(key, event.repeat) : !event.repeat;
        if (enabled && bindings.has(key) && fresh && !editing() && !inputBlocked()
            && !event.isComposing && !event.ctrlKey && !event.altKey && !event.metaKey
            && (stopping || feedback.stopping || feedback.home_active)) {
            event.preventDefault();
            showInputStatus(true);
            return;
        }
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
        if (!["escape", "[", "]"].includes(key) && !bindings.has(key)) return;
        event.preventDefault();
        if (!fresh || keys.has(key)) return;
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
        physicalKeys.release(key);
    }
    function poll() {
        if (disposed) return;
        const now = performance.now(),
            delayed = lastTick && now - lastTick > 200;
        lastTick = now;
        if (!enabled || !allowed || inputBlocked() || editing() || delayed)
            halt();
        const nextJog = () => continuousTool() ? lastSentAt + 50 : repeatAt;
        if (heldKeys.size && now >= nextJog() && !busy && !stopping) {
            repeating = true;
            repeatAt = now + 50;
            issue(heldKeys, true);
        }
        for (const cap of mapping.querySelectorAll(".key-cap")) {
            const replayKey = cap.dataset.key.replace(/^arrow/, "");
            cap.dataset.pressed = String(replayInput
                ? replayInput.keys.some(key => key === cap.dataset.key || key === replayKey) : keys.has(cap.dataset.key));
            cap.disabled = !enabled || !allowed;
        }
        // Timers may fire just before the requested deadline. Wait only the
        // remainder so a held tool jog does not fall from 20 Hz to 10 Hz.
        const delay = heldKeys.size && !busy && !stopping
            ? Math.max(1, Math.min(50, nextJog() - performance.now())) : 50;
        timer = setTimeout(poll, delay);
    }
    window.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);
    window.addEventListener("blur", halt);
    document.addEventListener("visibilitychange", halt);
    let timer = setTimeout(poll, 50);
    let replayInput = null;
    let manualMode = null;
    return {
        element: container,
        arms,
        roll: rollControls,
        get inlineFeedback() { return !cartesian(); },
        replay(input) {
            replayInput = input?.device === "keyboard" ? input : null;
            if (replayInput && manualMode === null) manualMode = group.value;
            const mode = replayInput?.mode;
            const selection = replayInput ? mode === "joints" && toolControl ? "joints:0" : mode : manualMode;
            if (selection && selection !== group.value && [...group.options].some(option => option.value === selection)) {
                group.value = selection;
                renderMapping();
            }
            if (!replayInput) manualMode = null;
            mapping.dataset.replay = String(Boolean(replayInput));
        },
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
            for (const cap of mapping.querySelectorAll(".key-cap"))
                cap.disabled = !on || !available;
        },
        feedback(state) {
            feedback = state || {};
            showFeedback();
            showInputStatus();
        },
        stop: halt,
        destroy() {
            disposed = true;
            physicalKeys.destroy();
            clearTimeout(timer);
            window.removeEventListener("keydown", keydown);
            window.removeEventListener("keyup", keyup);
            window.removeEventListener("blur", halt);
            document.removeEventListener("visibilitychange", halt);
            halt();
        },
    };
}
