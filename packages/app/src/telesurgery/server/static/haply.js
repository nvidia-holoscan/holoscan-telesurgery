// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { action, element } from "./ui.js";
import { inputBlocked } from "./robot-input.js";
import { axisTriad } from "./icons.js";

export const haplyName = "Haply Inverse3";
export const supportsHaply = robot =>
    !!(robot.controls?.mira_cartesian || robot.controls?.cartesian);

export function haplyInput(robot, send, stop, speeds) {
    const container = element("div", undefined, "gamepad-controls haply-controls");
    const dual = !!robot.controls?.mira_cartesian;
    const status = element("p", dual ? "Paused · Left arm" : "Paused", "gamepad-status");
    status.setAttribute("role", "status");
    const position = element("div", undefined, "haply-position");
    position.setAttribute("role", "group");
    position.title = "Measured position of the selected arm's working tip, in millimetres. Arrows show pen movement that increases each coordinate.";
    const positionLabel = element("div", "Arm tip · mm", "haply-position-label");
    position.append(positionLabel);
    const positionBody = element("div", undefined, "haply-position-body");
    const coordinates = element("div", undefined, "haply-coordinates");
    // Use the same pen-to-robot basis as the mapper, including older MIRA nodes.
    const config = dual ? robot.controls.mira_cartesian : robot.controls.cartesian;
    const basis = config.input_basis || config.haply_basis || [[0, 1, 0], [-1, 0, 0], [0, 0, 1]];
    const values = ["X", "Y", "Z"].map(axis => {
        const row = element("div", undefined, "haply-axis-value");
        const value = element("span", "—", "haply-coordinate");
        const label = element("span", axis);
        label.dataset.axis = axis;
        row.append(label, value);
        coordinates.append(row);
        return value;
    });
    positionBody.append(axisTriad(basis), coordinates);
    position.append(positionBody);
    let arm = "left", feedback = robot.state;
    function showFeedback(state = feedback) {
        feedback = state;
        const xyz = dual ? state?.cartesian_mm_deg?.[arm] : state?.tool_pose?.position_m;
        const armLabel = dual ? `${arm === "right" ? "Right" : "Left"} arm` : "Arm";
        position.setAttribute("aria-label", `${armLabel} tip position in millimetres`);
        values.forEach((value, index) => {
            const mm = Number.isFinite(xyz?.[index]) ? xyz[index] * (dual ? 1 : 1000) : NaN;
            value.textContent = Number.isFinite(mm) ? (Math.abs(mm) < 0.05 ? 0 : mm).toFixed(1) : "—";
        });
    }
    showFeedback();
    const arms = element("div", undefined, "motion-section");
    const roll = element("div", undefined, "motion-section");
    const grip = element("div", undefined, "haply-grip-hints");
    const hint = element("p", "", "input-discovery");
    const header = element("div", undefined, "haply-header");
    const calibrate = element("button", "Calibrate", "secondary small");
    const cancel = element("button", "Cancel", "secondary small");
    const range = element("div", undefined, "haply-range");
    const rangeStatus = element("strong");
    const rangeHint = element("p");
    const rangeTravel = element("p", "", "haply-travel");
    range.append(rangeStatus, rangeHint, rangeTravel);
    range.hidden = true;
    const calibrationError = element("p", "", "error-text haply-calibration-error");
    calibrationError.setAttribute("role", "alert");
    calibrationError.hidden = true;
    range.setAttribute("aria-live", "polite");
    const calibration = element("div", undefined, "haply-calibration");
    calibrate.type = cancel.type = "button";
    calibrate.setAttribute("aria-label", "Calibrate Haply movement range");
    calibrate.title = "Set the movement range by sweeping the pen. Acquiring robot control is not required.";
    cancel.hidden = true;
    calibration.append(calibrate, cancel);
    header.append(status, calibration);
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
    container.append(header, calibrationError, range, position, arms, roll, hint);
    container.hidden = true;
    let enabled = false, allowed = false, disposed = false, active = false;
    let token = crypto.randomUUID(), busy = false, lastTick = performance.now();
    let calibrationAction, collecting = false, calibrationFailure = "", savedUntil = 0;
    let pauseReason = "";
    const halt = (reason = "") => {
        token = crypto.randomUUID();
        status.textContent = status.textContent.replace(/^Active/, "Paused");
        if (reason) {
            pauseReason = reason;
            hint.textContent = reason;
            hint.hidden = false;
        }
        if (active) {
            active = false;
            Promise.resolve(stop()).catch(() => {});
        }
    };
    const blocked = () => !enabled || !allowed || inputBlocked();
    function requestCalibration(action) {
        halt();
        pauseReason = "";
        calibrationAction = action;
        calibrationFailure = "";
        calibrationError.hidden = true;
        calibrate.disabled = true;
        range.hidden = false;
        rangeStatus.textContent = action === "start" ? "Starting calibration… Robot paused."
            : action === "save" ? "Saving movement range…" : "Cancelling calibration…";
        rangeHint.textContent = rangeTravel.textContent = "";
    }
    calibrate.onclick = () => requestCalibration(collecting ? "save" : "start");
    cancel.onclick = () => requestCalibration("cancel");
    async function poll() {
        const now = performance.now();
        if (now - lastTick > 200 && active)
            halt("Control input was delayed; tap Start to resume.");
        if (blocked() && active)
            halt("Control paused; return to this window and tap Start to resume.");
        lastTick = now;
        if (disposed || !enabled || busy) return;
        const issued = now, generation = token, motionEnabled = !blocked();
        busy = true;
        const requestedCalibration = calibrationAction;
        calibrationAction = undefined;
        try {
            const result = await action("haply.read", {
                id: robot.id, token: generation, enabled: motionEnabled, speeds: speeds(),
                ...(requestedCalibration ? {calibration: requestedCalibration} : {}),
            });
            if (disposed || generation !== token) return;
            if (performance.now() - issued >= 200) {
                halt("Control input was delayed; tap Start to resume.");
                return;
            }
            const paused = result.paused || !motionEnabled || blocked();
            arm = result.arm === "right" ? "right" : "left";
            status.textContent = `${paused ? "Paused" : "Active"}${dual ? ` · ${arm === "right" ? "Right" : "Left"} arm` : ""}`;
            showFeedback();
            if (!paused || !motionEnabled) pauseReason = "";
            else if (result.error && !result.tracking_error) pauseReason = result.error;
            hint.textContent = result.error || pauseReason;
            hint.hidden = !hint.textContent;
            if (result.calibration) {
                collecting = result.calibration.collecting;
                calibrate.disabled = result.tracking_ready === false;
                calibrate.textContent = collecting ? "Save range" : result.calibration.ready ? "Recalibrate" : "Calibrate";
                cancel.hidden = !collecting;
                if (requestedCalibration === "save" && result.calibration.ready)
                    savedUntil = performance.now() + 4000;
                else if (requestedCalibration) savedUntil = 0;
                range.hidden = !collecting && performance.now() >= savedUntil;
                rangeStatus.textContent = collecting ? "Calibration active · Robot paused" : "Movement range saved";
                rangeHint.textContent = collecting
                    ? "Sweep left/right, forward/back and up/down, then save."
                    : "Center the pen, then tap Start.";
                rangeTravel.textContent = collecting ? `Travel: ${result.calibration.span_mm.join(" / ")} mm` : "";
                if (requestedCalibration) calibrationFailure = "";
                calibrationError.textContent = result.tracking_error || calibrationFailure;
                calibrationError.hidden = !calibrationError.textContent;
                if (collecting || hint.textContent === calibrationError.textContent) hint.hidden = true;
            }
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
                halt(error.message);
                if (requestedCalibration) {
                    calibrationFailure = error.message;
                    calibrationError.textContent = calibrationFailure;
                    calibrationError.hidden = false;
                    hint.hidden = true;
                    range.hidden = !collecting;
                    rangeStatus.textContent = "Calibration active · Robot paused";
                    rangeHint.textContent = "Continue the sweep, then save.";
                    calibrate.disabled = false;
                }
            }
        } finally { busy = false; }
    }
    const timer = setInterval(poll, 50);
    return {
        element: container, arms, roll, grip,
        feedback: showFeedback,
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
