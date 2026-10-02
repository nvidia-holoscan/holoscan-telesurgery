// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, element, button, device } from "./ui.js";
import { openLog } from "./logs.js";
const nodeName = (node) =>
    node.environment && node.id === "host"
        ? `${node.environment.toUpperCase()} simulation`
        : node.id === "host"
          ? `Host · ${node.name}`
          : node.name;
export function patientPages(
    changed,
    connectNode,
    removeNode,
    configureEnvironment,
) {
    let state, signature, identitySignature;
    const current = () => {
        const [page, id] = location.hash.slice(1).split("/");
        let node = null;
        try {
            node = id ? decodeURIComponent(id) : null;
        } catch {
            /* Unknown node returns to directory. */
        }
        if ((!page || page === "nodes") && state?.nodes?.length === 1)
            return { page: "node", node: state.nodes[0].id };
        return {
            page: ["nodes", "node", "surgeons"].includes(page)
                ? page
                : "overview",
            node,
        };
    };
    window.addEventListener("hashchange", changed);
    function status(node) {
        const line = element("div", undefined, "node-status-line");
        const simulation =
            node.id === "host" ? state.simulation : node.simulation;
        const loading =
            node.status === "online" && simulation?.status === "loading";
        line.append(
            element(
                "span",
                loading
                    ? "Preparing simulation"
                    : simulation?.status === "error" && node.status === "online"
                      ? "Simulation error"
                      : node.status === "unpaired"
                        ? "Needs pairing"
                        : node.status,
                `status ${loading ? "starting" : node.status}`,
            ),
        );
        if (node.id === "host" && state.simulation) {
            const log = button(
                "Logs",
                () =>
                    openLog(
                        `${nodeName(node)} · Simulator log`,
                        "/api/simulation/log",
                    ),
                "text-link",
                "logs",
            );
            log.setAttribute("aria-label", `${node.name} simulator logs`);
            line.append(log);
        }
        if (node.id !== "host") {
            if (node.connection === "service" && !node.paired)
                line.append(
                    button(
                        "Pair node",
                        () => connectNode(node.address),
                        "text-link",
                    ),
                );
            const label = simulation
                ? "Simulation logs"
                : node.connection === "service"
                  ? "Connection logs"
                  : "Deployment logs";
            const log = button(
                label,
                () =>
                    openLog(
                        `${nodeName(node)} · ${label}`,
                        `/api/nodes/${encodeURIComponent(node.id)}/log${simulation ? "?source=simulation" : ""}`,
                    ),
                "text-link",
                "logs",
            );
            log.setAttribute("aria-haspopup", "dialog");
            line.append(log);
            const remove = button(
                `Remove ${nodeName(node)}`,
                () => removeNode(node),
                "text-link icon-button node-remove",
                "remove",
            );
            remove.setAttribute("aria-haspopup", "dialog");
            line.append(remove);
        }
        return line;
    }
    function link(text, target) {
        const node = element("a", text, "activity-link");
        node.href = target;
        return node;
    }
    return {
        current,
        update(next) {
            state = next;
            const { page, node: id } = current();
            for (const section of document.querySelectorAll("[data-page]"))
                section.hidden = section.dataset.page !== page;
            for (const item of document.querySelectorAll("[data-page-link]")) {
                if (
                    item.dataset.pageLink === (page === "node" ? "nodes" : page)
                )
                    item.setAttribute("aria-current", "page");
                else item.removeAttribute("aria-current");
            }
            const selected = state.nodes?.find((node) => node.id === id);
            $("#device-workspace").hidden = page !== "node" || !selected;
            if (page === "node" && !selected) {
                location.hash = "nodes";
                return;
            }
            $("#patient-node-header").hidden = !selected;
            $("#node-environment").hidden =
                !selected ||
                selected.id === "host" ||
                selected.connection === "service";
            $("#node-environment").disabled = selected?.status !== "online";
            $("#node-environment").onclick = () =>
                configureEnvironment(selected);
            $("#camera-panel").hidden = !selected;
            $("#add-node").hidden = Boolean(state.environment);
            const heading = $(
                selected ? "#node-actions" : "#nodes-page .page-heading",
            );
            if ($("#add-node").parentElement !== heading)
                heading.append($("#add-node"));
            $("#patient-node-header .back-link").hidden =
                state.nodes?.length === 1;
            const identityKey = JSON.stringify([
                selected,
                state.simulation?.status,
            ]);
            if (selected && identitySignature !== identityKey) {
                identitySignature = identityKey;
                $("#node-name").textContent = nodeName(selected);
                $("#node-identity").replaceChildren(
                    status(selected),
                    element(
                        "span",
                        `SDK ${String(selected.sdk || state.sdk).split(".")[0]}`,
                        "muted",
                    ),
                    element(
                        "span",
                        selected.environment
                            ? `${selected.environment.toUpperCase()} simulation`
                            : "Physical devices",
                        "muted",
                    ),
                );
            }
            const simulation =
                selected?.id === "host"
                    ? state.simulation
                    : selected?.simulation;
            const loading = simulation?.status === "loading";
            $("#simulation-progress").hidden = !(
                simulation && simulation.status !== "ready"
            );
            $("#simulation-progress").textContent = loading
                ? `${simulation.stage || "Preparing your simulation room"} · ${simulation.elapsed || 0}s elapsed. Cameras appear automatically when ready.`
                : simulation?.status === "error"
                  ? "Simulation could not start. Open Logs to inspect the error."
                  : "";
            const pending =
                state.surgeons?.filter((s) => s.status === "pending") || [];
            $("#nav-node-count").textContent = state.nodes?.length || 0;
            $("#nav-request-count").textContent = pending.length || "";
            $("#node-count").textContent =
                state.nodes?.filter((n) => n.status === "online").length || 0;
            $("#camera-count").textContent =
                state.cameras?.filter((c) => c.status === "live").length || 0;
            $("#people-count").textContent =
                state.surgeons?.filter((s) => s.status === "approved").length ||
                0;
            $("#robot-count").textContent =
                state.robots?.filter(
                    (r) => r.status === "online" && !r.owner && !r.error,
                ).length || 0;
            const key = JSON.stringify([
                state.nodes,
                (state.cameras || []).map(({ frames, ...camera }) => camera),
                state.robots?.map(({ state, ...robot }) => robot),
                state.surgeons,
                state.simulation?.status,
                state.simulation?.stage,
            ]);
            if (signature !== key) {
                signature = key;
                const attention = $("#attention");
                attention.replaceChildren(
                    ...pending.map((s) =>
                        link(
                            `${s.name} requested ${s.requested_robot ? "video and robot" : "video"} access →`,
                            "#surgeons",
                        ),
                    ),
                );
                for (const node of state.nodes || []) {
                    const sim =
                        node.id === "host" ? state.simulation : node.simulation;
                    if (sim && sim.status !== "ready")
                        attention.append(
                            link(
                                `${nodeName(node)} · ${sim.status === "loading" ? "Simulation is warming up" : "Simulation needs attention"} →`,
                                `#node/${node.id}`,
                            ),
                        );
                }
                for (const node of state.nodes || [])
                    if (
                        ["error", "offline", "deploying", "unpaired"].includes(
                            node.status,
                        )
                    )
                        attention.append(
                            link(
                                `${nodeName(node)} · ${node.status} →`,
                                `#node/${node.id}`,
                            ),
                        );
                for (const item of [
                    ...(state.cameras || []),
                    ...(state.robots || []),
                ])
                    if (item.error)
                        attention.append(
                            link(
                                `${item.name} · ${item.error}`,
                                `#node/${item.node || item.id.split(":")[0]}`,
                            ),
                        );
                if (!attention.children.length)
                    attention.append(
                        element(
                            "p",
                            "No issues need attention.",
                            "quiet-state",
                        ),
                    );
                const activity = $("#room-activity");
                activity.replaceChildren();
                const directory = $("#nodes");
                directory.replaceChildren();
                for (const node of state.nodes || []) {
                    const cameras = (state.cameras || []).filter(
                        (c) => (c.node || c.id.split(":")[0]) === node.id,
                    );
                    const robots = (state.robots || []).filter(
                        (r) => (r.node || r.id.split(":")[0]) === node.id,
                    );
                    const detail =
                        node.connection === "service" && !node.paired
                            ? node.status === "offline"
                                ? "Waiting for service"
                                : "Pair to discover cameras and robots"
                            : `${cameras.filter((c) => c.status === "live").length}/${cameras.length} cameras streaming · ${robots.length} robots`;
                    const card = device(nodeName(node), detail);
                    card.querySelector("strong").title = nodeName(node);
                    const counts = element("div", undefined, "node-resources");
                    for (const [label, value] of [
                        ["Cameras", cameras.length],
                        [
                            "Streaming",
                            cameras.filter((c) => c.status === "live").length,
                        ],
                        ["Robots", robots.length],
                    ]) {
                        const item = element("div");
                        item.append(
                            element("strong", value),
                            element("span", label),
                        );
                        counts.append(item);
                    }
                    card.querySelector("small").textContent =
                        `${node.connection === "service" ? "Node service" : node.id === "host" ? "Local host" : "SSH node"} · SDK ${String(node.sdk || state.sdk).split(".")[0]}`;
                    card.append(counts);
                    card.append(status(node));
                    if (node.error)
                        card.append(
                            element(
                                "p",
                                "Connection failed. Open logs for details.",
                                "error-text",
                            ),
                        );
                    const open = link("Open node →", `#node/${node.id}`);
                    open.className = "node-open";
                    card.append(open);
                    directory.append(card);
                    activity.append(
                        link(
                            `${nodeName(node)} · ${detail}`,
                            `#node/${node.id}`,
                        ),
                    );
                }
                for (const robot of state.robots || [])
                    if (robot.owner)
                        activity.append(
                            link(
                                `${robot.name} · controlled by ${robot.owner}`,
                                `#node/${robot.node || robot.id.split(":")[0]}`,
                            ),
                        );
            }
        },
    };
}
