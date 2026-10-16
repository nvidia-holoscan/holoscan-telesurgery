// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, action, element, button, device } from "./ui.js";
import { openLog } from "./logs.js";
import { icon } from "./icons.js";
import { deviceStatus } from "./device-status.js";
const nodeName = (node) => node.name;
function uptimeText(node) {
    const seconds = node.uptime_s;
    let duration = "—";
    if (Number.isFinite(seconds) && seconds >= 0) {
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor(seconds / 3600) % 24;
        const minutes = Math.floor(seconds / 60) % 60;
        duration = days ? `${days}d ${hours}h ${minutes}m`
            : hours ? `${hours}h ${minutes}m`
            : minutes ? `${minutes}m` : `${Math.floor(seconds)}s`;
    }
    const label = node.status === "online" ? "Uptime" : "Last uptime";
    return `${label} ${duration}`;
}
function uptime(node) {
    const value = element("span", uptimeText(node), "node-uptime");
    value.dataset.nodeUptime = node.id;
    value.title = node.status === "online"
        ? "Time since the node service started; reconnecting does not reset it."
        : "Last reported node service uptime before disconnection.";
    return value;
}
export function patientPages(changed, removeNode, refresh) {
    let state, signature, identitySignature;
    $("#preview-devices").onclick = () =>
        $("#equipment-panel").scrollIntoView({ block: "start" });
    const current = () => {
        const [page, id] = location.hash.slice(1).split("/");
        let node = null;
        try {
            node = id ? decodeURIComponent(id) : null;
        } catch {
            /* Unknown node returns to directory. */
        }
        if (
            (!page || page === "nodes") &&
            state?.nodes?.length === 1 &&
            !state.node_requests?.length
        )
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
        const summary = element("div", undefined, "node-status-summary");
        const simulation = node.simulation;
        const loading =
            node.status === "online" && simulation?.status === "loading";
        summary.append(
            element(
                "span",
                loading
                    ? "Preparing simulation"
                    : simulation?.status === "error" && node.status === "online"
                      ? "Simulation error"
                      : node.status,
                `status ${loading ? "starting" : node.status}`,
            ),
            uptime(node),
        );
        line.append(summary);
        const label = simulation ? "Simulation logs" : "Node logs";
        const log = button(
            "Logs",
            () =>
                openLog(
                    `${nodeName(node)} · ${label}`,
                    `/api/nodes/${encodeURIComponent(node.id)}/log${simulation ? "?source=simulation" : ""}`,
                ),
            "text-link",
            "logs",
        );
        log.title = label;
        log.setAttribute("aria-label", label);
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
            for (const value of document.querySelectorAll("[data-node-uptime]")) {
                const node = state.nodes?.find(node => node.id === value.dataset.nodeUptime);
                if (node) value.textContent = uptimeText(node);
            }
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
            $("#camera-panel").hidden = !selected;
            $("#patient-node-header .back-link").hidden =
                state.nodes?.length === 1;
            const identityKey = JSON.stringify(selected && {...selected, uptime_s: undefined});
            if (selected && identitySignature !== identityKey) {
                identitySignature = identityKey;
                $("#node-name").textContent = nodeName(selected);
                $("#node-identity").replaceChildren(
                    status(selected),
                    element(
                        "span",
                        selected.environment
                            ? `${selected.environment.toUpperCase()} simulation`
                            : "Physical devices",
                        "muted",
                    ),
                );
            }
            const simulation = selected?.simulation;
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
            const requests = state.node_requests || [];
            const empty = !state.nodes?.length;
            $("#room-start").hidden = !empty;
            $("#summary").hidden = empty;
            $("#overview-page .overview-grid").hidden =
                empty && !requests.length && !pending.length;
            $("#node-start").hidden = !empty || requests.length > 0;
            $("#node-command").hidden = empty && !requests.length;
            $("#node-requests-panel").hidden = !requests.length;
            $("#nav-node-count").textContent = requests.length
                ? `${requests.length} pending`
                : state.nodes?.length || "";
            $("#nav-request-count").textContent = pending.length || "";
            $("#node-count").textContent =
                state.nodes?.filter((n) => n.status === "online").length || 0;
            $("#camera-count").textContent =
                state.cameras?.filter((c) => c.status === "live").length || 0;
            $("#people-count").textContent =
                state.surgeons?.filter((s) => s.status === "approved").length ||
                0;
            $("#robot-count").textContent =
                state.robots?.filter((r) => r.status === "online").length || 0;
            $("#node-total").textContent =
                `${state.nodes?.length || 0} nodes in this room`;
            $("#camera-total").textContent =
                `${state.cameras?.length || 0} cameras discovered`;
            $("#people-total").textContent = pending.length
                ? `${pending.length} awaiting approval`
                : "Patient-managed access";
            $("#robot-total").textContent =
                `${state.robots?.length || 0} controllers discovered`;
            const key = JSON.stringify([
                state.nodes?.map(({uptime_s, ...node}) => node),
                (state.cameras || []).map(({ frames, ...camera }) => camera),
                state.robots?.map(
                    ({ state, feedback_age_ms, ...robot }) => robot,
                ),
                state.surgeons,
                state.node_requests,
            ]);
            if (signature !== key) {
                signature = key;
                const requestsList = $("#node-requests");
                requestsList.replaceChildren();
                for (const request of requests) {
                    const row = element("div", undefined, "node-request");
                    const identity = element("div");
                    identity.append(
                        element("strong", request.name),
                        element(
                            "small",
                            `${request.ip} · ${request.environment ? `${request.environment.toUpperCase()} simulation` : "Physical devices"} · ${request.id}`,
                        ),
                    );
                    const actions = element("div", undefined, "actions");
                    for (const [label, method] of [
                        ["Approve", "node.approve"],
                        ["Reject", "node.reject"],
                    ]) {
                        const control = button(
                            label,
                            async () => {
                                for (const button of actions.children)
                                    button.disabled = true;
                                try {
                                    await action(method, { id: request.id });
                                    await refresh();
                                } finally {
                                    for (const button of actions.children)
                                        button.disabled = false;
                                }
                            },
                            label === "Approve" ? "small" : "secondary small",
                        );
                        actions.append(control);
                    }
                    row.append(icon("server"), identity, actions);
                    requestsList.append(row);
                }
                const attention = $("#attention");
                attention.replaceChildren(
                    ...pending.map((s) =>
                        link(
                            `${s.name} requested ${s.requested_robot ? "video and robot" : "video"} access →`,
                            "#surgeons",
                        ),
                    ),
                );
                for (const request of requests)
                    attention.append(
                        link(
                            `${request.name} requests node access →`,
                            "#nodes",
                        ),
                    );
                for (const node of state.nodes || []) {
                    const sim = node.simulation;
                    if (sim && sim.status !== "ready")
                        attention.append(
                            link(
                                `${nodeName(node)} · ${sim.status === "loading" ? "Simulation is warming up" : "Simulation needs attention"} →`,
                                `#node/${node.id}`,
                            ),
                        );
                }
                for (const node of state.nodes || [])
                    if (["error", "offline", "starting"].includes(node.status))
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
                    if (item.error && item.controller?.status !== "stopped")
                        attention.append(
                            link(
                                `${item.name} · ${item.error}`,
                                `#node/${item.node || item.id.split(":")[0]}`,
                            ),
                        );
                $("#attention-count").hidden = !attention.children.length;
                $("#attention-count").textContent = attention.children.length;
                if (!attention.children.length)
                    attention.append(
                        element(
                            "p",
                            "All nodes connected. No pending requests.",
                            "quiet-state",
                        ),
                    );
                const activity = $("#room-activity");
                activity.replaceChildren();
                const directory = $("#nodes");
                directory.replaceChildren();
                const nodes = [...(state.nodes || [])].sort((a, b) =>
                    nodeName(a).localeCompare(nodeName(b), undefined, {
                        numeric: true,
                        sensitivity: "base",
                    }),
                );
                const groups = {};
                for (const [status, label] of [
                    ["online", "Online"],
                    ["offline", "Offline"],
                ]) {
                    const count = nodes.filter((node) =>
                        status === "online"
                            ? node.status === "online"
                            : node.status !== "online",
                    ).length;
                    if (!count) continue;
                    const group = element("section", undefined, "node-group");
                    group.dataset.status = status;
                    const heading = element("h2", label);
                    heading.id = `nodes-${status}-heading`;
                    heading.append(element("span", count, "node-group-count"));
                    group.setAttribute("aria-labelledby", heading.id);
                    groups[status] = element("div", undefined, "node-card-grid");
                    group.append(heading, groups[status]);
                    directory.append(group);
                }
                for (const node of nodes) {
                    const cameras = (state.cameras || []).filter(
                        (c) => (c.node || c.id.split(":")[0]) === node.id,
                    );
                    const robots = (state.robots || []).filter(
                        (r) => (r.node || r.id.split(":")[0]) === node.id,
                    );
                    const detail = `${cameras.filter((c) => c.status === "live").length}/${cameras.length} cameras streaming · ${robots.length} robot${robots.length === 1 ? "" : "s"}`;
                    const card = device(nodeName(node), detail);
                    const identity = element(
                        "a",
                        undefined,
                        "node-card-identity",
                    );
                    identity.href = `#node/${node.id}`;
                    const text = element("div");
                    text.append(...card.childNodes);
                    identity.append(icon("server"), text, icon("right"));
                    card.append(identity);
                    card.querySelector("strong").title = nodeName(node);
                    const counts = element("a", undefined, "node-resources");
                    counts.href = `#node/${node.id}`;
                    counts.setAttribute(
                        "aria-label",
                        `${nodeName(node)} equipment`,
                    );
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
                    card.querySelector("small").textContent = [
                        node.ip,
                        node.environment ? `${node.environment.toUpperCase()} simulation` : "Physical devices",
                    ]
                        .filter(Boolean)
                        .join(" · ");
                    card.append(status(node), counts);
                    const equipment = element(
                        "div",
                        undefined,
                        "node-equipment",
                    );
                    for (const item of [...cameras, ...robots]) {
                        const row = link("", `#node/${node.id}`);
                        const [label, tone] = deviceStatus(
                            item,
                            robots.includes(item),
                        );
                        row.title = label;
                        row.setAttribute(
                            "aria-label",
                            `${item.name}: ${label}`,
                        );
                        row.dataset.status = tone;
                        row.append(
                            icon(cameras.includes(item) ? "camera" : "robot"),
                            element("span", item.name, "node-equipment-name"),
                        );
                        equipment.append(row);
                    }
                    if (!equipment.children.length)
                        equipment.append(
                            element(
                                "p",
                                node.status === "online"
                                    ? "Discovering connected devices…"
                                    : "Waiting for node connection",
                            ),
                        );
                    card.append(equipment);
                    if (node.error)
                        card.append(
                            element(
                                "p",
                                "Connection failed. Open logs for details.",
                                "error-text",
                            ),
                        );
                    groups[node.status === "online" ? "online" : "offline"].append(card);
                    const roomNode = link("", `#node/${node.id}`);
                    roomNode.classList.add("room-node");
                    const roomIdentity = element("div");
                    roomIdentity.append(
                        element("strong", nodeName(node)),
                        element("small", detail),
                    );
                    roomNode.append(
                        icon("server"),
                        roomIdentity,
                        element("span", node.status, `status ${node.status}`),
                        icon("right"),
                    );
                    activity.append(roomNode);
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
