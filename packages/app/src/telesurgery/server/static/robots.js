// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, element, button, action, notice } from "./ui.js";
export function robotControls(refresh, openMetrics) {
    let state,
        signature,
        moving = false,
        motion = null,
        renewing = false;
    const held = new Set();
    async function move(robot, index, direction, arm) {
        if (motion) return;
        const current = { robot: robot.id, release: false };
        motion = current;
        moving = true;
        try {
            while (moving) {
                const command =
                    robot.kind === "franka-sim"
                        ? { joints: Array(7).fill(0) }
                        : { left: Array(4).fill(0), right: Array(4).fill(0) };
                command[arm][index] = direction * 0.4;
                try {
                    await action("robot.move", { id: robot.id, command });
                    if (current.release) {
                        await action("robot.release", { id: robot.id });
                        held.delete(robot.id);
                        break;
                    }
                    held.add(robot.id);
                } catch (error) {
                    moving = false;
                    held.delete(robot.id);
                    notice(error);
                }
                await new Promise((resolve) => setTimeout(resolve, 50));
            }
        } finally {
            motion = null;
            moving = false;
        }
    }
    function stopMotion() {
        moving = false;
    }
    window.addEventListener("pointerup", stopMotion);
    window.addEventListener("pointercancel", stopMotion);
    async function releaseAll() {
        moving = false;
        if (motion) motion.release = true;
        for (const id of held) {
            held.delete(id);
            try {
                await action("robot.release", { id });
            } catch {
                /* watchdog handles connection loss */
            }
        }
    }
    window.addEventListener("blur", releaseAll);
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) releaseAll();
    });
    window.addEventListener("pagehide", () => {
        moving = false;
        if (motion) motion.release = true;
        for (const id of held)
            fetch("/api/action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                keepalive: true,
                body: JSON.stringify({
                    action: "robot.release",
                    params: { id },
                }),
            });
    });
    function renderRobots(data) {
        const container = $("#robots");
        // Preserve held buttons while input is active; status refresh must not interrupt pointer capture.
        if (motion) return;
        container.replaceChildren();
        if (!data.robots?.length)
            container.append(
                element(
                    "p",
                    state.simulation?.status === "loading"
                        ? "Robot controls will appear when the room is ready."
                        : "No robot controller discovered.",
                ),
            );
        for (const robot of data.robots || []) {
            const card = element("div", undefined, "robot");
            card.append(
                element("strong", robot.name),
                element(
                    "p",
                    robot.owner
                        ? `Controlled by ${robot.owner}`
                        : "Available",
                ),
            );
            if (robot.error) card.append(element("p", robot.error));
            if (robot.state?.targets_deg) {
                const pose = Object.entries(robot.state.targets_deg)
                    .map(
                        ([arm, values]) =>
                            `${arm}: ${values.map((v) => v.toFixed(1)).join(", ")}`,
                    )
                    .join(" · ");
                card.append(
                    element(
                        "p",
                        `Joint targets (°) — ${pose}`,
                        "robot-state",
                    ),
                );
            }
            if (state.role === "patient") {
                if (robot.owner || robot.error)
                    card.append(
                        button(
                            robot.error ? "Retry hold" : "Revoke control",
                            async () => {
                                await action("robot.revoke", {
                                    id: robot.id,
                                });
                                await refresh();
                            },
                            "danger small",
                        ),
                    );
            } else if (state.session.robot) {
                card.append(
                    element(
                        "p",
                        "Hold + or − to move. Control is acquired automatically.",
                    ),
                );
                const mine = robot.owner_id === state.session.id;
                if (mine) {
                    held.add(robot.id);
                    card.append(
                        button("Release control", async () => {
                            moving = false;
                            if (motion?.robot === robot.id)
                                motion.release = true;
                            held.delete(robot.id);
                            await action("robot.release", { id: robot.id });
                            await refresh();
                        }),
                    );
                }
                const controls = element("div", undefined, "joint-groups");
                const arms =
                    robot.kind === "franka-sim"
                        ? [["joints", 7]]
                        : [
                              ["left", 4],
                              ["right", 4],
                          ];
                for (const [arm, count] of arms) {
                    const group = element("div", undefined, "joint-group");
                    if (arm !== "joints")
                        group.append(element("h3", `${arm} arm`));
                    const joints = element("div", undefined, "joint-grid");
                    for (let index = 0; index < count; index++) {
                        const joint = element("div", undefined, "joint");
                        joint.append(
                            element(
                                "span",
                                `${arm === "joints" ? "Joint" : arm} ${index + 1}`,
                            ),
                        );
                        for (const direction of [-1, 1]) {
                            const control = button(
                                direction < 0 ? "−" : "+",
                                () => {},
                            );
                            control.setAttribute(
                                "aria-label",
                                `${robot.name} ${arm} ${index + 1} ${direction < 0 ? "decrease" : "increase"}`,
                            );
                            control.disabled =
                                (!!robot.owner && !mine) ||
                                !!robot.error ||
                                robot.status !== "online";
                            control.addEventListener(
                                "pointerdown",
                                (event) => {
                                    if (
                                        !motion &&
                                        event.button === 0 &&
                                        event.isPrimary
                                    ) {
                                        event.preventDefault();
                                        control.setPointerCapture(
                                            event.pointerId,
                                        );
                                        move(robot, index, direction, arm);
                                    }
                                },
                            );
                            joint.append(control);
                            control.addEventListener("keydown", (event) => {
                                if (!["Space", "Enter"].includes(event.code))
                                    return;
                                event.preventDefault();
                                if (!event.repeat && !motion)
                                    move(robot, index, direction, arm);
                            });
                            control.addEventListener("keyup", (event) => {
                                if (["Space", "Enter"].includes(event.code)) {
                                    event.preventDefault();
                                    stopMotion();
                                }
                            });
                        }
                        joints.append(joint);
                    }
                    group.append(joints);
                    controls.append(group);
                }
                card.append(controls);
            } else card.append(element("p", "View-only access"));
            const metrics = button(
                "Metrics",
                () => openMetrics(robot.id),
                "text-link",
                "chart",
            );
            metrics.setAttribute("aria-label", `${robot.name} robot metrics`);
            card.append(metrics);
            container.append(card);
        }
    }

    setInterval(async () => {
        if (renewing) return;
        renewing = true;
        try {
            for (const id of held) {
                try {
                    await action("robot.renew", { id });
                } catch {
                    held.delete(id);
                    moving = false;
                }
            }
        } finally {
            renewing = false;
        }
    }, 500);

    return {
        releaseAll,
        update(next, data) {
            state = next;
            const key = JSON.stringify([
                data.robots,
                state.session?.robot,
                state.simulation?.status,
            ]);
            if (!motion && key !== signature) {
                renderRobots(data);
                signature = key;
            }
            if (
                state.role === "surgeon" &&
                state.session?.status !== "approved"
            ) {
                moving = false;
                held.clear();
            }
        },
    };
}
