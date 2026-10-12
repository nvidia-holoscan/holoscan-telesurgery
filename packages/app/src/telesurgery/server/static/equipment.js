// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, element, button, codecName, hasSelection } from "./ui.js";
import { robotStatus } from "./robots.js";
import { icon } from "./icons.js";
import { deviceStatus } from "./device-status.js";

export function equipmentTable(changed, cameraCard, robotActions) {
    const dialog = $("#device-detail-dialog"),
        rows = $("#equipment-rows");
    let selected, node, signature;
    $("#close-device-detail").onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
        selected = null;
    });
    function open(item) {
        selected = item.id;
        $("#device-detail-title").textContent = `${item.type} details`;
        changed();
        dialog.showModal();
    }
    return {
        get selected() {
            return selected;
        },
        close() {
            dialog.close();
        },
        update(data, currentNode, viewState) {
            if (node !== currentNode) {
                dialog.close();
                selected = null;
                node = currentNode;
            }
            const cameras = data.cameras || [],
                robots = data.robots || [];
            const items = [
                ...cameras.map((item) => ({ ...item, type: "Camera" })),
                ...robots.map((item) => ({ ...item, type: "Robot" })),
            ];
            if (selected && !items.some((item) => item.id === selected))
                dialog.close();
            $("#equipment-count").textContent =
                `${cameras.length} camera${cameras.length === 1 ? "" : "s"} · ${robots.length} robot${robots.length === 1 ? "" : "s"}`;
            $("#equipment-empty").hidden = items.length > 0;
            const key = JSON.stringify([
                items.map(
                    ({ state, frames, feedback_age_ms, ...item }) => item,
                ),
                viewState,
            ]);
            if (key === signature || hasSelection(rows)) return;
            signature = key;
            rows.replaceChildren();
            for (const item of items) {
                const row = element("tr");
                row.dataset.device = item.id;
                function cell(label, content) {
                    const td = element("td");
                    td.dataset.label = label;
                    td.append(content);
                    row.append(td);
                    return td;
                }
                const name = button(
                    item.name,
                    () => open(item),
                    "equipment-name",
                );
                name.setAttribute("aria-haspopup", "dialog");
                name.prepend(icon(item.type === "Camera" ? "camera" : "robot"));
                cell("Device", name);
                cell("Type", element("span", item.type, "device-type"));
                const [label, tone] = deviceStatus(item, item.type === "Robot");
                const status =
                    item.type === "Robot" ? robotStatus(item) : label;
                cell("Status", element("span", status, `status ${tone}`));
                const details = cell(
                    "Details",
                    element(
                        "span",
                        item.type === "Camera"
                            ? `${item.width} × ${item.height} · ${codecName(item.codec)} · ${Number(Number(item.fps || 0).toFixed(1))} FPS`
                            : item.simulation
                              ? "Simulation"
                              : item.controls?.read_only
                                ? "Physical · State only"
                                : `Physical · ${Object.keys(item.controls?.groups || {}).length ? "Motion enabled" : "Motion disabled"}`,
                    ),
                );
                if (item.encoding_error)
                    details.append(element("p", item.encoding_error, "encoding-warning"));
                const actions =
                    item.type === "Camera"
                        ? cameraCard(item).querySelector(".actions")
                        : robotActions(item);
                cell("Actions", actions);
                rows.append(row);
            }
        },
    };
}
