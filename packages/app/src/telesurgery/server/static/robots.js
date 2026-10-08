// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, element, button, action, notice, hasSelection } from "./ui.js";
import { gamepadInput } from "./gamepad.js";
import { keyboardInput } from "./keyboard.js";
import { gripperControls } from "./grippers.js";
import { jogGroups, gripSpeed, jointStep, jointSpeed } from "./robot-input.js";
import { openLog } from "./logs.js";
import { robotStartup } from "./robot-start.js";
import { deviceStatus } from "./device-status.js";
import { setIcon } from "./icons.js";

export function robotLabel(robot) {
    return `${robot.name} · ${robot.simulation ? "Simulation" : "Physical"}`;
}

export function robotStatus(robot) {
    const [label, status] = deviceStatus(robot, true);
    if (status !== "online") return label;
    if (robot.owner) return `Controlled by ${robot.owner}`;
    if (robot.controls?.read_only) return "State only";
    if (!jogGroups(robot).length) return "Motion disabled";
    return label;
}

function renderFeedback(container, robot) {
    if (hasSelection(container)) return;
    const state = robot.state || {},
        joints = state.joints_deg || state.targets_deg,
        mira = robot.kind === "mira" || robot.kind === "mira-sim";
    container.hidden = !joints;
    container.title = state.feedback_source || "";
    container.replaceChildren();
    if (!joints) return;
    const heading = element("div", undefined, "feedback-heading");
    heading.append(
        element(
            "span",
            state.joints_deg ? "Measured joints (°)" : "Joint targets (°)",
        ),
    );
    if (state.mode || robot.stale)
        heading.append(
            element(
                "span",
                robot.stale ? "Stale feedback" : state.mode,
                "feedback-mode",
            ),
        );
    container.append(heading);
    for (const [group, values] of Object.entries(joints)) {
        if (group !== "joints")
            container.append(element("div", group, "feedback-group"));
        const row = element("div", undefined, "feedback-joints");
        const displayed = values.slice(
            0,
            robot.controls?.groups?.[group] || (mira ? 5 : values.length),
        );
        displayed.forEach((value, index) => {
            const cell = element("div");
            cell.append(
                element(
                    "small",
                    mira && index === 4 ? "Roll" : `J${index + 1}`,
                ),
                element("span", value.toFixed(robot.simulation ? 1 : 2)),
            );
            const velocity = state.velocity_deg_s?.[group]?.[index],
                torque = state.effort_nm?.[group]?.[index];
            cell.title = [
                Number.isFinite(velocity)
                    ? `${velocity.toFixed(2)} degrees per second`
                    : "",
                Number.isFinite(torque) ? `${torque.toFixed(2)} Nm` : "",
            ]
                .filter(Boolean)
                .join(" · ");
            row.append(cell);
        });
        container.append(row);
    }
}

export function robotControls(refresh, openMetrics) {
    const startRobot = robotStartup(refresh);
    let state,
        visible = [],
        signature,
        current = null;
    const cards = new Map(),
        acknowledgements = new Map(),
        stepping = new Map(),
        releasing = new Map(),
        held = new Set();
    function stopInputs(card) {
        card?.gamepad?.stop();
        card?.keyboard?.stop();
        card?.grippers?.stop();
    }
    function motionState(robot) {
        const reply = acknowledgements.get(robot.id);
        return reply && reply.sequence > (robot.state?.sequence ?? -1)
            ? reply
            : robot.state || {};
    }
    function acknowledge(id, result) {
        if (
            !Number.isInteger(result?.sequence) ||
            result.sequence <= (acknowledgements.get(id)?.sequence ?? -1)
        )
            return;
        acknowledgements.set(id, result);
        const card = cards.get(id);
        if (card && (result.stopping || result.home_active)) {
            card.keyboard?.feedback(result);
            card.keyboard?.update(card.mode?.value === "keyboard", false);
            card.gamepad?.update(card.mode?.value !== "keyboard", false);
            card.grippers?.update(false, card.mode?.value === "keyboard");
        }
    }
    function connectionButton(robot) {
        const connected = robot.connection_enabled;
        const control = button(
            connected ? "Disconnect" : "Connect",
            async () => {
                if (
                    !connected &&
                    robot.controller &&
                    robot.controller.status !== "running"
                ) {
                    startRobot(robot);
                    return;
                }
                await action(connected ? "robot.disconnect" : "robot.connect", {
                    id: robot.id,
                });
                await refresh();
            },
            "secondary small",
        );
        control.disabled = robot.node_online === false;
        control.title = connected
            ? "Release this application's robot connection"
            : "Connect to the robot controller";
        return control;
    }
    function permitted(robot) {
        return (
            state.role === "surgeon" &&
            state.session?.status === "approved" &&
            state.session.robot &&
            robot.status === "online" &&
            !robot.stale &&
            !robot.error &&
            (!robot.owner || robot.owner_id === state.session.id)
        );
    }
    async function release(id) {
        if (releasing.has(id)) return releasing.get(id);
        if (current?.id === id) current.cancelled = true;
        held.delete(id);
        const pending = action("robot.release", { id });
        releasing.set(id, pending);
        try {
            acknowledge(id, await pending);
            stepping.delete(id);
        } catch (error) {
            notice(error);
        } finally {
            releasing.delete(id);
        }
    }
    async function stop() {
        const pending = current;
        if (pending) {
            pending.cancelled = true;
            await pending.done;
        }
    }
    async function send(robot, command, mode = "jog") {
        if (current || releasing.has(robot.id) || !permitted(robot)) return;
        const feedback = motionState(robot);
        if (feedback.stopping || feedback.home_active) {
            stopInputs(cards.get(robot.id));
            return;
        }
        let complete;
        const input = {
            id: robot.id,
            cancelled: false,
            done: new Promise((resolve) => {
                complete = resolve;
            }),
        };
        current = input;
        try {
            const result = await action("robot.move", {
                id: robot.id,
                command,
                mode,
                ...(cards.get(robot.id)?.speed
                    ? { speed_deg_s: cards.get(robot.id).speed.value() }
                    : {}),
            });
            acknowledge(robot.id, result);
            if (mode === "jog") stepping.delete(robot.id);
            held.add(robot.id);
            return result;
        } catch (error) {
            input.cancelled = true;
            stopInputs(cards.get(robot.id));
            notice(error);
        } finally {
            if (input.cancelled || !permitted(robot)) await release(robot.id);
            current = null;
            complete();
        }
    }
    async function endInput(id) {
        await stop();
        if (held.has(id)) await release(id);
        if (releasing.has(id)) await releasing.get(id);
    }
    async function step(robot, command, mode = "step") {
        if (current || releasing.has(robot.id)) return;
        stepping.set(robot.id, Infinity);
        const result = await send(robot, command, mode);
        if (result?.control_active) stepping.set(robot.id, result.sequence);
        else stepping.delete(robot.id);
    }
    async function releaseAll() {
        if (current) current.cancelled = true;
        for (const card of cards.values()) stopInputs(card);
        await stop();
        for (const id of [...held]) await release(id);
        await Promise.allSettled([...releasing.values()]);
    }
    window.addEventListener("blur", releaseAll);
    window.addEventListener("keydown", (event) => {
        if (event.key === "Escape") releaseAll();
    });
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) releaseAll();
    });
    window.addEventListener("pagehide", () => {
        for (const id of new Set([...held, ...(current ? [current.id] : [])])) {
            fetch("/api/action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                keepalive: true,
                body: JSON.stringify({
                    action: "robot.release",
                    params: { id },
                }),
            });
        }
    });
    function render() {
        for (const card of cards.values()) {
            card.gamepad?.destroy();
            card.keyboard?.destroy();
            card.grippers?.destroy();
        }
        cards.clear();
        const container = $("#robots");
        container.replaceChildren();
        if (!visible.length)
            container.append(
                element(
                    "p",
                    state.simulation?.status === "loading"
                        ? "Robot controls will appear when the room is ready."
                        : "No robot controller discovered.",
                ),
            );
        for (const robot of visible) {
            const element_ = element("div", undefined, "robot");
            const status = element("p"),
                error = element("p"),
                pose = element("div", "", "robot-state");
            const identity = element("div", undefined, "robot-identity");
            const detail = element("small", "", "robot-description");
            const statusLine = element("div", undefined, "robot-status-line");
            statusLine.append(status);
            detail.hidden = state.role !== "patient";
            identity.append(
                element("strong", robotLabel(robot), "robot-name"),
                detail,
                statusLine,
                error,
            );
            element_.append(identity, pose);
            const card = {
                robot,
                element: element_,
                status,
                error,
                pose,
                detail,
            };
            cards.set(robot.id, card);
            if (state.role === "patient") {
                const actions = element(
                    "div",
                    undefined,
                    "actions robot-actions",
                );
                card.actions = actions;
                if ("connection_enabled" in robot)
                    actions.append(connectionButton(robot));
                if (robot.controller) {
                    if (!("connection_enabled" in robot)) {
                        card.start = button("Bring online", () =>
                            startRobot(card.robot),
                        );
                        card.start.setAttribute("aria-haspopup", "dialog");
                        actions.append(card.start);
                    }
                    card.logs = button(
                        "Logs",
                        () =>
                            openLog(
                                `${robot.name} · Controller log`,
                                `/api/robots/${encodeURIComponent(robot.id)}/log`,
                            ),
                        "text-link",
                        "logs",
                    );
                    card.logs.setAttribute("aria-haspopup", "dialog");
                    actions.append(card.logs);
                }
                card.release = button(
                    "Revoke control",
                    async () => {
                        await action("robot.revoke", { id: robot.id });
                        await refresh();
                    },
                    "danger small",
                );
                actions.append(card.release);
                element_.append(actions);
            } else if (state.session?.robot && jogGroups(robot).length) {
                card.step = jointStep(robot, () => stopInputs(card));
                card.gamepad = gamepadInput(
                    robot,
                    (command) => send(card.robot, command),
                    () => endInput(robot.id),
                    card.step.value,
                );
                const mode = card.gamepad.select;
                card.mode = mode;
                card.release = button(
                    "Stop",
                    async () => {
                        stopInputs(card);
                        await stop();
                        await release(robot.id);
                        await refresh();
                    },
                    "danger small",
                );
                card.release.title =
                    "Esc: stop motion and release control; keep the controller connected";
                const shortcut = element("kbd", "Esc", "control-shortcut");
                shortcut.setAttribute("aria-hidden", "true");
                card.release.append(shortcut);
                const actions = element("div", undefined, "robot-toolbar");
                actions.append(mode);
                if (robot.controls.home_deg) {
                    card.home = button(
                        "Home",
                        async () => {
                            card.home.disabled = true;
                            card.home.blur();
                            stopInputs(card);
                            await endInput(robot.id);
                            await refresh();
                            await step(card.robot, {}, "home");
                            await refresh();
                        },
                        "secondary icon-button",
                        "home",
                    );
                    card.home.title = `Move to home: ${Object.values(robot.controls.home_deg).flat().join(", ")}°`;
                    actions.append(card.home);
                }
                actions.append(card.release);
                element_.append(actions);
                const settings = element("div", undefined, "motion-settings");
                settings.append(card.step.element);
                if (robot.controls.speed_deg_s) {
                    card.speed = jointSpeed(robot, () => stopInputs(card));
                    settings.append(card.speed.element);
                }
                element_.append(settings);
                card.keyboard = keyboardInput(
                    robot,
                    (command, continuous) =>
                        continuous
                            ? send(card.robot, command)
                            : step(card.robot, command),
                    () => endInput(robot.id),
                    card.step.value,
                );
                mode.onchange = async () => {
                    await releaseAll();
                    card.gamepad.update(
                        mode.value !== "keyboard",
                        permitted(card.robot),
                    );
                    card.keyboard.update(
                        mode.value === "keyboard",
                        permitted(card.robot),
                    );
                };
                card.gamepad.update(false, permitted(robot));
                card.keyboard.update(true, permitted(robot));
                element_.append(card.keyboard.element, card.gamepad.element);
                if (robot.controls.grippers?.length) {
                    card.gripSpeed = gripSpeed(robot, () => stopInputs(card));
                    settings.append(card.gripSpeed.element);
                    card.grippers = gripperControls(
                        robot,
                        (command) => send(card.robot, command, "grip"),
                        () => endInput(robot.id),
                        card.gripSpeed.value,
                    );
                    element_.append(card.grippers.element);
                }
            } else
                element_.append(
                    element(
                        "p",
                        state.session?.robot
                            ? robot.controls?.reason ||
                                  "Controller input is not supported."
                            : "View-only access",
                    ),
                );
            const metrics = button(
                "Metrics",
                () => openMetrics(robot.id),
                state.role === "surgeon"
                    ? "secondary small icon-button"
                    : "text-link",
                "chart",
            );
            metrics.setAttribute("aria-label", `${robot.name} robot metrics`);
            (state.role === "surgeon"
                ? statusLine
                : card.actions || element_
            ).append(metrics);
            container.append(element_);
        }
    }
    let renewing = false;
    setInterval(async () => {
        if (renewing || !held.size) return;
        renewing = true;
        try {
            for (const id of held) {
                try {
                    acknowledge(id, await action("robot.renew", { id }));
                } catch {
                    stopInputs(cards.get(id));
                    await endInput(id);
                }
            }
        } finally {
            renewing = false;
        }
    }, 500);
    return {
        patientActions(robot) {
            const actions = element(
                "div",
                undefined,
                "actions equipment-robot-actions",
            );
            if ("connection_enabled" in robot) {
                actions.append(connectionButton(robot));
                if (robot.controller)
                    actions.append(
                        button(
                            "Logs",
                            () =>
                                openLog(
                                    `${robot.name} · Controller log`,
                                    `/api/robots/${encodeURIComponent(robot.id)}/log`,
                                ),
                            "secondary small icon-button camera-logs",
                            "logs",
                        ),
                    );
            } else if (robot.controller) {
                const running = robot.controller.status === "running";
                const start = button(
                    robot.status === "online"
                        ? "Online"
                        : running
                          ? "Controller on"
                          : "Bring online",
                    () => startRobot(robot),
                    "secondary small",
                );
                start.disabled =
                    robot.node_online === false ||
                    robot.status === "online" ||
                    ["running", "unavailable"].includes(
                        robot.controller.status,
                    );
                start.setAttribute("aria-haspopup", "dialog");
                const logs = button(
                    "Logs",
                    () =>
                        openLog(
                            `${robot.name} · Controller log`,
                            `/api/robots/${encodeURIComponent(robot.id)}/log`,
                        ),
                    "secondary small icon-button camera-logs",
                    "logs",
                );
                logs.disabled = robot.node_online === false;
                logs.setAttribute("aria-haspopup", "dialog");
                actions.append(start, logs);
            } else {
                const status = button(
                    robot.status === "online" ? "Online" : "Offline",
                    () => {},
                    "secondary small",
                );
                status.disabled = true;
                actions.append(status);
            }
            const metrics = button(
                "Metrics",
                () => openMetrics(robot.id),
                "secondary small icon-button camera-metrics",
                "chart",
            );
            actions.append(metrics);
            return actions;
        },
        releaseAll,
        update(next, data) {
            state = next;
            visible = data.robots || [];
            const key = JSON.stringify([
                visible.map((r) => [
                    r.id,
                    r.name,
                    r.simulation,
                    r.controls,
                    Boolean(r.controller),
                    r.connection_enabled,
                ]),
                state.role,
                state.session?.robot,
            ]);
            if (key !== signature) {
                releaseAll();
                render();
                signature = key;
            }
            for (let robot of visible) {
                if (
                    robot.status !== "online" ||
                    (robot.state?.sequence ?? -1) >=
                        (acknowledgements.get(robot.id)?.sequence ?? -1)
                )
                    acknowledgements.delete(robot.id);
                robot = { ...robot, state: motionState(robot) };
                const card = cards.get(robot.id);
                card.robot = robot;
                if (
                    robot.status !== "online" ||
                    (!robot.state?.control_active &&
                        robot.state?.sequence >= stepping.get(robot.id))
                )
                    stepping.delete(robot.id);
                const mine =
                    state.role === "surgeon" &&
                    !!state.session?.id &&
                    robot.owner_id === state.session.id;
                card.status.textContent = robotStatus(robot);
                card.status.className = `status ${deviceStatus(robot, true)[1]}`;
                card.detail.textContent = robot.simulation
                    ? "Simulation controller"
                    : robot.controls?.read_only
                      ? "Joint feedback · State only"
                      : `Vendor controller · ${jogGroups(robot).length ? "Motion enabled" : "Motion disabled"}`;
                const failure =
                    robot.controller?.error ||
                    (robot.controller?.status === "stopped"
                        ? ""
                        : robot.error) ||
                    "";
                card.error.textContent = failure;
                card.error.hidden = !failure;
                if (card.start) {
                    card.start.disabled =
                        robot.node_online === false ||
                        robot.status === "online" ||
                        ["running", "unavailable"].includes(
                            robot.controller.status,
                        );
                    card.start.textContent =
                        robot.status === "online"
                            ? "Online"
                            : robot.controller.status === "running"
                              ? "Controller on"
                              : "Bring online";
                    card.logs.disabled = robot.node_online === false;
                }
                renderFeedback(card.pose, robot);
                if (card.release) {
                    card.release.hidden =
                        state.role === "patient"
                            ? !robot.owner &&
                              !(robot.error && robot.status === "online")
                            : false;
                    card.release.disabled =
                        state.role === "patient"
                            ? robot.status !== "online"
                            : robot.node_online === false ||
                              robot.status === "disconnected" ||
                              state.session?.status !== "approved" ||
                              (!!robot.owner && !mine);
                    if (state.role === "patient")
                        card.release.textContent = robot.error
                            ? "Retry hold"
                            : "Revoke control";
                }
                const allowed = permitted(robot);
                if (card.home) {
                    card.home.disabled =
                        !allowed ||
                        !!robot.state?.control_active ||
                        stepping.has(robot.id);
                    setIcon(
                        card.home,
                        "home",
                        robot.state?.home_active ? "Going home…" : "Home",
                    );
                    card.home.title = robot.state?.home_active
                        ? "Going home · Stop or Esc interrupts motion"
                        : `Home · ${Object.values(robot.controls.home_deg).flat().join(", ")}°`;
                }
                const inputAllowed =
                    allowed &&
                    !robot.state?.home_active &&
                    !robot.state?.stopping;
                if (card.mode) card.mode.disabled = !inputAllowed;
                card.step?.update(inputAllowed);
                card.speed?.update(inputAllowed);
                card.gripSpeed?.update(inputAllowed);
                card.grippers?.update(
                    inputAllowed,
                    card.mode?.value === "keyboard",
                );
                card.gamepad?.update(
                    card.mode?.value !== "keyboard",
                    inputAllowed,
                );
                card.keyboard?.update(
                    card.mode?.value === "keyboard",
                    inputAllowed,
                );
                card.keyboard?.feedback(robot.state);
                if (card.keyboard && card.mode.value === "keyboard") {
                    card.pose.hidden = true;
                }
                if (
                    !allowed &&
                    (held.has(robot.id) || current?.id === robot.id)
                )
                    endInput(robot.id);
                if (mine) held.add(robot.id);
            }
        },
    };
}
