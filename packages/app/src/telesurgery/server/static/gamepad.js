// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

import { element } from "./ui.js";
import { icon, setControllerKey } from "./icons.js";
import { normalizeGamepad } from "./gamepad-mapping.js";
import { haplyName, supportsHaply } from "./haply.js";
import {
    emptyJog,
    inputBlocked,
    jogGroups,
    pairedArms,
    miraToolJog,
} from "./robot-input.js";

const axis = (value) => {
    if (!Number.isFinite(value)) return 0;
    const size = Math.min(1, Math.abs(value));
    return size <= 0.15 ? 0 : (Math.sign(value) * (size - 0.15)) / 0.85;
};

function controllerName(id) {
    if (/dualsense|ps5\b|054c.*0ce6/i.test(id)) return "Sony DualSense";
    if (/dualshock|ps4\b|054c.*(05c4|09cc)/i.test(id)) return "Sony DualShock 4";
    if (/playstation|ps3\b|054c/i.test(id)) return "PlayStation controller";
    if (/nintendo|switch.*pro|joy.?con|057e/i.test(id)) return "Nintendo controller";
    if (/xbox|x-box|xinput|microsoft.*controller|045e/i.test(id)) return "Xbox controller";
    const name = id.replace(/\s*\([^)]*\)\s*/g, " ").trim();
    return name.length > 26 ? `${name.slice(0, 25)}…` : name || "Gamepad";
}

function controllerBindings(id) {
    const playstation = /dualsense|dualshock|054c|playstation|ps[345]\b/i.test(id);
    const nintendo = /nintendo|switch.*pro|joy.?con|057e/i.test(id);
    const xbox = /xbox|x-box|xinput|microsoft.*controller|045e/i.test(id);
    return {
        enable: playstation ? "L1" : nintendo ? "L" : xbox ? "LB" : "LB/L1",
        alternate: playstation ? "R1" : nintendo ? "R" : xbox ? "RB" : "RB/R1",
        rollUp: playstation ? "△" : nintendo ? "X" : xbox ? "Y" : "North",
        rollDown: playstation ? "✕" : nintendo ? "B" : xbox ? "A" : "South",
        home: playstation ? "PS button" : nintendo ? "Home button" : xbox ? "Xbox button" : "Guide button",
        homeFallback: playstation ? "Options" : nintendo ? "+" : xbox ? "Menu ☰" : "Start / Menu",
        z: "←",
        x: "→",
        n: playstation ? "□" : nintendo ? "Y" : xbox ? "X" : "West",
        m: playstation ? "○" : nintendo ? "A" : xbox ? "B" : "East",
    };
}

export function gamepadInput(
    robot, send, stop, stepSize = () => 0.2, gripSpeed = () => 20,
    { home = null, gripFeedback = () => {}, haplyAvailable = () => false, jointSpeed = null } = {},
) {
    const dual = pairedArms(robot);
    const franka = ["franka", "franka-sim"].includes(robot.kind) &&
        robot.controls.groups.joints === 7 && jogGroups(robot).length === 1;
    const toolControl = Boolean(robot.controls.cartesian);
    const jointCount = robot.controls.groups.joints;
    const bankedJoints = franka || (toolControl && jogGroups(robot).length === 1 && jointCount <= 8);
    let cartesian = toolControl;
    const shoulderGroups = dual || bankedJoints;
    const roll = dual && robot.controls.groups.left === 5;
    const grippers = robot.controls.grippers || [];
    const holdGrip = robot.kind === "versius-sim";
    const enabledTools = roll && grippers.length ? "arms, roll & grip"
        : roll ? "arms & roll" : grippers.length ? "arms & grip" : "movement";
    const container = element("div", undefined, "gamepad-controls");
    const device = document.createElement("select"),
        group = document.createElement("select");
    device.setAttribute("aria-label", `${robot.name} input`);
    device.title =
        "Keyboard or a connected gamepad. Press a gamepad button to detect it.";
    const keyboard = element("option", "Keyboard");
    keyboard.value = "keyboard";
    device.append(keyboard);
    const haply = supportsHaply(robot) ? element("option", haplyName) : null;
    if (haply) haply.value = "haply";
    const discovery = element("p", "Press a gamepad button to connect it here.", "input-discovery");
    discovery.hidden = true;
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
    const miraTool = Boolean(robot.controls.mira_cartesian);
    if (toolControl) {
        group.setAttribute("aria-label", `${robot.name} gamepad mode`);
        if (bankedJoints) {
            const option = element("option", "Individual joints (advanced)");
            option.value = "joints:0";
            group.replaceChildren(option);
        }
        const option = element("option", "Tool movement");
        option.value = "cartesian";
        group.prepend(option);
        group.value = "cartesian";
    } else if (miraTool) {
        group.replaceChildren();
        group.setAttribute("aria-label", `${robot.name} gamepad mode`);
        for (const [value, label] of [["joints", "Joint movement"], ["mira-tool", "Tool movement · X/Y/Z + elbow"]]) {
            const option = element("option", label);
            option.value = value;
            group.append(option);
        }
    }
    const miraCartesian = () => miraTool && group.value === "mira-tool";
    const jointVelocity = () => Boolean(jointSpeed && robot.controls.joint_velocity && !cartesian && !miraCartesian());
    const increment = (arm, index, seconds) => jointVelocity() ? jointSpeed(arm, index) : stepSize(arm, index, seconds);
    group.hidden = !toolControl && !miraTool && (shoulderGroups || group.options.length < 2);
    const status = element(
        "p",
        "Press a gamepad button to discover it.",
        "gamepad-status",
    );
    status.setAttribute("role", "status");
    function showHint(message) {
        if (status.textContent === message) return;
        status.textContent = message;
        status.title = message;
    }
    const instructions = element("div", undefined, "gamepad-instructions");
    const arms = element("div", undefined, "motion-section");
    const rollControls = element("div", undefined, "motion-section");
    const rollInstructions = element("div", undefined, "gamepad-instructions gamepad-roll");
    arms.append(instructions);
    rollControls.append(rollInstructions);
    rollControls.hidden = !roll;
    const enableKey = element("kbd"), alternateKey = element("kbd");
    const enableHint = element("span"), alternateHint = element("span", "Joints 3–4 · move sticks");
    const stickJoints = [];
    const positionHeadings = [];
    const cartesianKeys = [];
    let handPosition = robot.state?.grippers?.hand ?? null, gripTarget = null, handToggleReady = false;
    let feedback = robot.state || {};
    function renderMapping() {
        rollControls.hidden = !(roll || (cartesian && robot.controls.cartesian.independent_rotation));
        stickJoints.length = positionHeadings.length = cartesianKeys.length = 0;
        instructions.className = "gamepad-instructions";
        instructions.replaceChildren(enableKey, enableHint);
        if (shoulderGroups) instructions.append(alternateKey, alternateHint);
        if (cartesian) {
            instructions.className = "cartesian-mapping";
            instructions.replaceChildren();
            for (const [title, bindings] of [
                ["Left stick", [["↔", "Left / right", 0], ["↕", "Forward / back", 1]]],
                ["Right stick", [["↕", "Up / down", 3], ["↔", "Turn", 2]]],
                ["D-pad · tilt", [["↔", "Side to side", 4], ["↕", "Forward / back", 5]]],
            ]) {
                const section = element("div", undefined, "cartesian-directions");
                section.append(element("span", title, "cartesian-label"));
                for (const [symbol, label, index] of bindings) {
                    const row = element("div", undefined, "cartesian-direction");
                    const key = element("kbd", symbol);
                    key.setAttribute("aria-label", `${title}: ${label}`);
                    row.append(key, element("span", label));
                    section.append(row);
                    cartesianKeys.push({key, index});
                }
                instructions.append(section);
            }
            const frame = element("span", "Arm-base directions", "cartesian-frame");
            frame.title = "Relative to this arm’s fixed base: forward +X, left +Y, up +Z. Camera and tool rotation do not change these directions.";
            instructions.append(frame);
        } else if (bankedJoints) {
            instructions.className = "franka-gamepad";
            instructions.replaceChildren();
            for (const [bank, key, hint] of [[0, enableKey, enableHint], [1, alternateKey, alternateHint]]) {
                const section = element("div", undefined, "franka-joint-group");
                const heading = element("div", undefined, "gamepad-instructions");
                heading.append(key, hint);
                const sticks = element("div", undefined, "franka-sticks");
                for (let stick = 0; stick < 2; stick++) {
                    const column = element("div", undefined, "keyboard-rows");
                    if (bank === 0) {
                        const label = element("div", undefined, "franka-stick-heading");
                        const unit = element("span", "°");
                        positionHeadings.push(unit);
                        label.append(element("span", stick === 0 ? "Left stick" : "Right stick"), unit);
                        column.append(label);
                    }
                    for (let direction = 0; direction < 2; direction++) {
                        const axis = stick * 2 + direction, index = bank * 4 + axis;
                        if (index >= jointCount) continue;
                        const row = element("div", undefined, "franka-stick-joint");
                        row.dataset.joint = String(index);
                        const value = element("output", "—", "gamepad-joint-position");
                        const cap = element("kbd", direction ? "↕" : "↔");
                        cap.title = `${stick === 0 ? "Left" : "Right"} stick · ${direction ? "up increases, down decreases" : "right increases, left decreases"} J${index + 1}`;
                        cap.setAttribute("aria-label", cap.title);
                        row.append(element("span", `J${index + 1}`), value, cap);
                        column.append(row);
                        stickJoints.push({index, bank, axis, value, cap});
                    }
                    sticks.append(column);
                }
                section.append(heading, sticks);
                instructions.append(section);
            }
        }
        showFeedback(feedback);
    }
    function showFeedback(state = {}) {
        feedback = state;
        handPosition = Number.isFinite(state?.grippers?.hand) ? state.grippers.hand : null;
        const measured = Boolean(state?.joints_deg);
        const values = (state?.joints_deg || state?.targets_deg)?.joints;
        const label = measured ? "Measured position" : "Target position";
        for (const unit of positionHeadings) {
            unit.textContent = measured ? "°" : "Target °";
            unit.title = `${label} in degrees`;
        }
        for (const joint of stickJoints) {
            const value = values?.[joint.index];
            joint.value.textContent = Number.isFinite(value) ? value.toFixed(robot.simulation ? 1 : 2) : "—";
            joint.value.setAttribute("aria-label", `J${joint.index + 1} ${label.toLowerCase()} in degrees`);
            joint.value.title = state?.feedback_source || label;
        }
    }
    renderMapping();
    const leftRollKeys = ["up", "down"].map(direction => {
        const key = element("kbd");
        key.append(icon(direction));
        return key;
    });
    const rightRollKeys = [element("kbd"), element("kbd")];
    if (roll) {
        for (const [label, keys] of [["Left", leftRollKeys], ["Right", rightRollKeys]]) {
            const arm = element("div", undefined, "gamepad-roll-arm");
            const bindings = element("div", undefined, "gamepad-roll-keys");
            bindings.append(...keys);
            arm.append(element("span", label), bindings);
            rollInstructions.append(arm);
        }
    }
    const badges = () => [enableKey, alternateKey, ...leftRollKeys, ...rightRollKeys, ...stickJoints.map(j => j.cap), ...cartesianKeys.map(b => b.key)];
    let replayInput = null;

    function showReplayInput(input) {
        const down = index => input.buttons.includes(index);
        const axes = input.axes.map(axis), alternate = down(5);
        enableKey.dataset.active = String(down(4) && !alternate);
        alternateKey.dataset.active = String(down(4) && alternate);
        for (const joint of stickJoints)
            joint.cap.dataset.active = String(down(4) && joint.bank === Number(alternate) && axes[joint.axis] !== 0);
        for (const [keys, positive, negative] of [[leftRollKeys, 12, 13], [rightRollKeys, 3, 0]]) {
            keys[0].dataset.active = String(down(positive) && !down(negative));
            keys[1].dataset.active = String(down(negative) && !down(positive));
        }
        const values = [...axes, Number(down(14)) - Number(down(15)), Number(down(13)) - Number(down(12))];
        for (const binding of cartesianKeys)
            binding.key.dataset.active = String(values[binding.index] !== 0);
        const velocity = {};
        for (const arm of grippers) {
            const [close, open] = arm === "left" ? [14, 15] : [2, 1];
            velocity[arm] = Number(down(open)) - Number(down(close));
        }
        gripFeedback(velocity);
        showHint("Replay inputs · Stop / Esc to cancel");
        container.dataset.state = "replay";
    }
    container.append(group, status, arms, rollControls);
    let allowed = false,
        enabled = false,
        disposed = false,
        armed = false;
    let signature = "",
        restoreSelection = null,
        waitForDevice = false,
        selectedId = "",
        active = false,
        busy = false,
        stopping = false,
        alternate = false,
        lastMode = "",
        jointActive = false,
        lastJogAt = 0,
        lastSentAt = -Infinity,
        lastGrip = "",
        homeReady = false,
        homeStartedAt = null,
        homeHeldButton = null,
        lastTick = 0;
    const halt = () => {
        armed = false;
        homeReady = false;
        homeStartedAt = null;
        homeHeldButton = null;
        jointActive = false;
        lastJogAt = 0;
        lastGrip = "";
        gripTarget = null;
        handToggleReady = false;
        gripFeedback({});
        for (const badge of badges()) badge.dataset.active = "false";
        if (active) {
            active = false;
            stopping = true;
            Promise.resolve(stop()).finally(() => { stopping = false; });
        }
    };
    const selectionChanged = () => device.dispatchEvent(new CustomEvent("change", {
        detail: {automatic: true},
    }));
    device.addEventListener("change", event => {
        if (!event.detail?.automatic) restoreSelection = null;
        selectedId = "";
        halt();
    });
    group.onchange = () => {
        halt();
        cartesian = toolControl && group.value === "cartesian";
        renderMapping();
    };
    function poll() {
        if (disposed) return;
        for (const badge of badges()) badge.dataset.active = "false";
        gripFeedback({});
        let pads;
        try {
            pads = Array.from(navigator.getGamepads?.() || []).map(normalizeGamepad).filter(
                (p) => p?.connected,
            );
        } catch {
            halt();
            discovery.hidden = false;
            discovery.textContent = "Gamepad access is unavailable in this browser.";
            showHint(discovery.textContent);
            timer = setTimeout(poll, 1000);
            return;
        }
        discovery.hidden = device.value === "haply" || !pads.length || pads.some(p => p.mapping === "standard");
        discovery.textContent = typeof navigator.getGamepads !== "function"
            ? "Gamepad access requires a supported browser on localhost or HTTPS."
            : pads.length
              ? "This controller does not provide a supported button mapping."
              : "Press a gamepad button to connect it here.";
        const hasHaply = haply && haplyAvailable();
        const next = JSON.stringify([hasHaply, pads.map((p) => [p.index, p.id, p.mapping])]);
        if (next !== signature) {
            signature = next;
            const selected = device.value;
            device.replaceChildren(keyboard);
            if (hasHaply) device.append(haply);
            for (const pad of pads) {
                const name = controllerName(pad.id);
                const duplicate = pads.filter(p => controllerName(p.id) === name).length > 1;
                const option = element(
                    "option",
                    name + (duplicate ? ` · ${pad.index + 1}` : "") +
                        (pad.mapping === "standard"
                            ? ""
                            : " · unsupported mapping"),
                );
                option.value = String(pad.index);
                option.title = pad.id;
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
                selectionChanged();
            }
        }
        if (restoreSelection) {
            const previous = restoreSelection;
            const matching = pads.filter(p => p.mapping === "standard" &&
                controllerName(p.id) === previous.name);
            const match = "id" in previous
                ? pads.find(p => p.index === previous.index && p.id === previous.id && p.mapping === "standard")
                : matching.length === previous.count ? matching[previous.ordinal] : null;
            const restoreHaply = hasHaply && previous.name === haplyName;
            if (match || restoreHaply || !waitForDevice) {
                restoreSelection = null;
                device.value = restoreHaply ? "haply" : match ? String(match.index) : "keyboard";
                selectionChanged();
            }
        }
        const pad = pads.find((p) => String(p.index) === device.value);
        device.title = device.value === "haply" ? "Haply connected to the surgeon service's host"
            : pad?.id || "To use a gamepad, connect it and press a button, then select it here.";
        const { enable, alternate: alternateButton, rollUp, rollDown, home: logoButton, homeFallback } = controllerBindings(pad?.id || "");
        const guidance = cartesian ? "Release controls to stop"
            : `Hold ${enable} for ${enabledTools}`;
        enableKey.textContent = enable;
        alternateKey.textContent = `${enable} + ${alternateButton}`;
        enableHint.textContent = dual ? miraCartesian() ? "X / Y · move sticks" : "Joints 1–2 · move sticks"
            : bankedJoints ? "Joints 1–4" : "Hold to move · release to stop";
        alternateHint.textContent = bankedJoints ? `Joints 5–${jointCount}` : miraCartesian() ? "Z / elbow · move sticks" : "Joints 3–4 · move sticks";
        setControllerKey(rightRollKeys[0], rollUp);
        setControllerKey(rightRollKeys[1], rollDown);
        for (const [keys, arm, buttons] of [
            [leftRollKeys, "left", ["D-pad ↑", "D-pad ↓"]],
            [rightRollKeys, "right", [rollUp, rollDown]],
        ]) keys.forEach((key, index) => {
            key.title = `${index === 0 ? "Increase" : "Decrease"} ${arm} tool roll · hold ${enable} + ${buttons[index]}`;
            key.setAttribute("aria-label", key.title);
        });
        const now = performance.now(),
            delayed = lastTick && now - lastTick > 200;
        lastTick = now;
        if (replayInput) {
            showReplayInput(replayInput);
            timer = setTimeout(poll, 50);
            return;
        }
        const blocked = !enabled || !allowed || stopping || inputBlocked();
        if (
            blocked ||
            !pad ||
            pad.mapping !== "standard" ||
            delayed ||
            (selectedId && selectedId !== pad.id)
        ) {
            halt();
            showHint(!pad
                ? "Choose a connected gamepad."
                : guidance);
        } else {
            selectedId = pad.id;
            const axes = [
                axis(pad.axes[0]),
                -axis(pad.axes[1]),
                axis(pad.axes[2]),
                -axis(pad.axes[3]),
            ];
            const down = index => Boolean(pad.buttons[index]?.pressed);
            const rollPressed = cartesian ? [12, 13, 14, 15].some(down)
                : roll && [12, 13, 3, 0].some(down);
            const rollDirection = {
                left: Number(down(12)) - Number(down(13)),
                right: Number(down(3)) - Number(down(0)),
            };
            const gripButtons = { left: [14, 15], right: [2, 1], hand: holdGrip || !cartesian ? [2, 1] : [] };
            const velocity = {};
            let gripPressed = false;
            for (const arm of grippers) {
                const [close, open] = gripButtons[arm] || [];
                const closing = Boolean(pad.buttons[close]?.pressed);
                const opening = Boolean(pad.buttons[open]?.pressed);
                gripPressed ||= closing || opening;
                velocity[arm] = (Number(opening) - Number(closing)) * gripSpeed() / 100;
            }
            if (cartesian && !holdGrip) {
                gripPressed = grippers.includes("hand") && down(2);
                if (!gripPressed) handToggleReady = true;
            }
            // Tool-space Franka input needs only a deliberate motion from
            // neutral. After any interruption, held controls cannot re-arm it.
            const pressed = cartesian
                ? axes.some(v => v !== 0) || rollPressed || gripPressed || gripTarget !== null
                : Boolean(pad.buttons[4]?.pressed);
            const nextAlternate = !cartesian && shoulderGroups && down(5);
            if (nextAlternate !== alternate) {
                // Either shoulder can be pressed first while input is already
                // armed and idle. Never remap moving or interrupted input.
                const idle = armed && !active && !busy &&
                    axes.every(v => v === 0) && !gripPressed && !rollPressed;
                if (!idle) halt();
                alternate = nextAlternate;
            }
            const homeButtons = home ? [16, 9].filter(down) : [];
            const homePressed = homeButtons.length > 0;
            const homeButton = homeButtons.map(index => index === 16 ? logoButton : homeFallback).join(" and ");
            if (!homePressed) {
                homeReady = true;
                homeStartedAt = null;
                homeHeldButton = null;
            }
            if (homePressed) {
                const neutral = !pressed && axes.every(v => v === 0) &&
                    !gripPressed && !rollPressed && !active && !busy && home.available();
                armed = false;
                // One continuous hold of one shortcut. Overlapping or swapping
                // buttons requires releasing both before a fresh request.
                const sameButton = homeHeldButton === null || homeHeldButton === homeButtons[0];
                if (!neutral || homeButtons.length !== 1 || !sameButton) {
                    halt();
                    showHint(`Release ${homeButton} and controls`);
                } else if (!homeReady) {
                    showHint(`Release ${homeButton} before requesting Home`);
                } else {
                    homeHeldButton = homeButtons[0];
                    homeStartedAt ??= now;
                    const remaining = Math.max(0, 1000 - (now - homeStartedAt));
                    showHint(`Hold ${homeButton} for Home · ${(remaining / 1000).toFixed(1)}s`);
                    if (!remaining) {
                        homeReady = false;
                        homeStartedAt = null;
                        showHint(guidance);
                        Promise.resolve(home.run()).catch(halt);
                    }
                }
            } else if (!pressed) {
                if (active) {
                    halt();
                }
                armed = axes.every((v) => v === 0) && !gripPressed && !rollPressed;
                showHint(armed
                    ? guidance
                    : rollPressed ? cartesian ? "Release D-pad and center sticks" : "Release roll buttons and center sticks"
                    : (grippers.length ? "Center sticks and release gripper buttons" : "Center sticks before enabling"));
            } else if (armed) {
                showHint(guidance);
                enableKey.dataset.active = String(!alternate);
                alternateKey.dataset.active = String(alternate);
                for (const joint of stickJoints)
                    joint.cap.dataset.active = String(joint.bank === Number(alternate) && axes[joint.axis] !== 0);
                for (const [keys, direction] of [[leftRollKeys, rollDirection.left], [rightRollKeys, rollDirection.right]]) {
                    keys[0].dataset.active = String(roll && direction > 0);
                    keys[1].dataset.active = String(roll && direction < 0);
                }
                if (cartesian) {
                    if (!holdGrip && gripPressed && handToggleReady && handPosition !== null) {
                        gripTarget = (gripTarget ?? handPosition) > 0.5 ? 0 : 1;
                        handToggleReady = false;
                    }
                    if (gripTarget !== null && handPosition !== null) {
                        const distance = gripTarget - handPosition;
                        if (Math.abs(distance) <= 0.015) gripTarget = null;
                        else velocity.hand = Math.sign(distance) * gripSpeed() / 100;
                    }
                    const values = [...axes, Number(down(14)) - Number(down(15)), Number(down(13)) - Number(down(12))];
                    for (const binding of cartesianKeys)
                        binding.key.dataset.active = String(values[binding.index] !== 0);
                }
                gripFeedback(velocity);
                const command = cartesian ? {
                    translation: [axes[1], -axes[0], axes[3]],
                    rotation: [Number(down(14)) - Number(down(15)), Number(down(13)) - Number(down(12)), -axes[2]],
                } : emptyJog(robot);
                // Scale the latest input by elapsed time, including ticks used
                // for grippers, without catching up a stall with a large jump.
                const seconds = jointActive && lastJogAt
                    ? Math.min(0.1, (now - lastJogAt) / 1000) : 0.05;
                if (cartesian) {
                    // Velocity requests are scaled and integrated by the node.
                } else if (dual) {
                    const offset = alternate ? 2 : 0;
                    for (const [arm, start] of [
                        ["left", 0],
                        ["right", 2],
                    ]) {
                        for (let i = 0; i < 2; i++)
                            command[arm][offset + i] = axes[start + i] * increment(arm, offset + i, seconds);
                        if (roll) command[arm][4] = rollDirection[arm] * increment(arm, 4, seconds);
                    }
                } else {
                    const [key, start] = group.value.split(":"),
                        offset = bankedJoints ? (alternate ? 4 : 0) : Number(start);
                    axes.forEach((v, i) => {
                        if (offset + i < command[key].length)
                            command[key][offset + i] = v * increment(key, offset + i, seconds);
                    });
                }
                const movingJoints = Object.values(command).flat().some(v => v !== 0);
                const movingGrips = Object.values(velocity).some(v => v !== 0);
                const gripSignature = JSON.stringify(velocity);
                if (!movingJoints && !movingGrips) {
                    if (active) {
                        active = false;
                        jointActive = false;
                        lastJogAt = 0;
                        lastGrip = "";
                        stop();
                    }
                } else if (!busy && now - lastSentAt >= 50) {
                    // One current command per tick, never queue a second command
                    // behind a slow reply. Send changed gripper rates (including
                    // zeros) first, then alternate independent arm/gripper updates.
                    const needsGrip = movingGrips || (lastGrip && gripSignature !== lastGrip);
                    const needsJog = movingJoints || jointActive;
                    const mode = needsGrip && (
                        !needsJog || gripSignature !== lastGrip || lastMode !== "grip"
                    ) ? "grip" : "jog";
                    if (mode === "grip") lastGrip = gripSignature;
                    else {
                        jointActive = movingJoints;
                        lastJogAt = now;
                    }
                    lastMode = mode;
                    lastSentAt = now;
                    active = busy = true;
                    send(mode === "grip" ? { velocity } : miraCartesian() ? miraToolJog(robot, command) : command,
                        mode === "jog" ? miraCartesian() ? "cartesian" : jointVelocity() ? "velocity" : mode : mode)
                        .catch(halt)
                        .finally(() => {
                            busy = false;
                            // Re-sample as soon as a slow reply permits the
                            // next 20 Hz tick. Waiting another whole timer
                            // period can expire the node's 200 ms watchdog.
                            // Input is read again; no motion is queued/replayed.
                            if (!disposed) {
                                clearTimeout(timer);
                                schedule();
                            }
                        });
                }
            } else
                showHint(cartesian
                    ? "Center sticks and release D-pad to resume"
                    : `Release ${enable}${roll || grippers.length ? " and tool buttons" : ""}; center sticks to enable`);
        }
        container.dataset.state = active ? "moving" : armed ? "ready" : "paused";
        if (!disposed) schedule();
    }
    function schedule() {
        // Timers can fire just before the 50 ms send deadline. Recheck at the
        // deadline instead of skipping another whole tick (halving the rate).
        const remaining = lastSentAt + 50 - performance.now();
        timer = setTimeout(poll, active && !busy
            ? Math.max(1, Math.ceil(remaining)) : 50);
    }
    let timer = setTimeout(poll, 50);
    return {
        select: device,
        discovery,
        bindings: () => ({
            ...(device.value === "haply" ? {haply: true} : {}),
            ...controllerBindings(device.selectedOptions[0]?.title || ""),
            toggleGrip: cartesian && !holdGrip,
            enableRequired: !cartesian,
        }),
        selection: () => device.value === "keyboard" ? null : device.value === "haply"
            ? {name: haplyName, ordinal: 0, count: 1} : {
            index: Number(device.value), id: device.selectedOptions[0]?.title,
        },
        handoff() {
            if (device.value === "keyboard") return null;
            if (device.value === "haply") return {name: haplyName, ordinal: 0, count: 1};
            const name = controllerName(device.selectedOptions[0].title);
            const matching = [...device.options].filter(option => option.value !== "keyboard" &&
                !option.disabled && controllerName(option.title) === name);
            return {name, ordinal: matching.indexOf(device.selectedOptions[0]), count: matching.length};
        },
        restore(selection, {wait = false} = {}) {
            restoreSelection = selection;
            waitForDevice = wait;
        },
        element: container,
        arms,
        roll: rollControls,
        get inlineFeedback() { return bankedJoints && !cartesian; },
        replay(input) {
            replayInput = input?.device === "gamepad" ? input : null;
            if (!replayInput) {
                for (const badge of badges()) badge.dataset.active = "false";
                gripFeedback({});
            }
        },
        feedback: showFeedback,
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
