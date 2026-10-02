// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, button, notice } from "./ui.js";
import { setIcon } from "./icons.js";
export function viewingLayout() {
    let key,
        order = [],
        mode = "auto",
        editing = false,
        dragged;
    function save() {
        try {
            localStorage.setItem(key, JSON.stringify({ order, mode }));
        } catch {
            /* Layout remains usable without storage. */
        }
    }
    function apply() {
        $("#videos").dataset.layout = mode;
        $("#videos").classList.toggle("editing", editing);
        $("#view-layout").value = mode;
        $("#edit-layout").setAttribute("aria-pressed", String(editing));
        setIcon(
            $("#edit-layout"),
            editing ? "check" : "layout",
            editing ? "Done arranging" : "Edit layout",
        );
        for (const tile of $("#videos").children) {
            const position = order.indexOf(tile.dataset.camera);
            tile.style.order = Math.max(0, position);
            tile.classList.toggle("primary", position === 0);
            tile.querySelector(".tile-arrange").hidden = !editing;
            tile.querySelector('[data-move="-1"]').disabled = position <= 0;
            tile.querySelector('[data-move="1"]').disabled =
                position >= order.length - 1;
        }
    }
    function move(id, destination) {
        const from = order.indexOf(id);
        if (from < 0 || destination < 0 || destination >= order.length)
            return;
        order.splice(from, 1);
        order.splice(destination, 0, id);
        save();
        apply();
    }
    $("#view-layout").onchange = (event) => {
        mode = event.target.value;
        save();
        apply();
    };
    $("#edit-layout").onclick = () => {
        editing = !editing;
        apply();
    };
    $("#workspace-fullscreen").onclick = async () => {
        try {
            if (document.fullscreenElement) await document.exitFullscreen();
            else await $("#operating-workspace").requestFullscreen();
        } catch (error) {
            notice(error);
        }
    };
    document.addEventListener("fullscreenchange", () => {
        setIcon(
            $("#workspace-fullscreen"),
            document.fullscreenElement ? "collapse" : "expand",
            document.fullscreenElement ? "Exit fullscreen" : "Fullscreen",
        );
    });
    return {
        update(state) {
            const next = `telesurgery-layout:${state.patient || "local"}`;
            if (key !== next) {
                key = next;
                try {
                    const saved = JSON.parse(
                        localStorage.getItem(key) || "{}",
                    );
                    mode = ["auto", "two", "focus"].includes(saved.mode)
                        ? saved.mode
                        : "auto";
                    order = Array.isArray(saved.order)
                        ? saved.order.filter((id) => typeof id === "string")
                        : [];
                } catch {
                    order = [];
                    mode = "auto";
                }
            }
            const ids = [...$("#videos").children].map(
                (tile) => tile.dataset.camera,
            );
            order = [
                ...order.filter((id) => ids.includes(id)),
                ...ids.filter((id) => !order.includes(id)),
            ];
            apply();
        },
        attach(tile, camera) {
            const controls = document.createElement("div");
            controls.className = "tile-arrange";
            controls.hidden = true;
            const handle = button(
                "Drag to arrange",
                () => {},
                "text-link drag-handle",
            );
            handle.draggable = true;
            handle.setAttribute(
                "aria-label",
                `Drag ${camera.name} to arrange`,
            );
            handle.addEventListener("dragstart", (event) => {
                if (!editing) {
                    event.preventDefault();
                    return;
                }
                dragged = camera.id;
                event.dataTransfer.setData("text/plain", camera.id);
            });
            handle.addEventListener("dragend", () => {
                dragged = null;
            });
            tile.addEventListener("dragover", (event) => {
                if (editing && dragged) event.preventDefault();
            });
            tile.addEventListener("drop", (event) => {
                if (editing && dragged) {
                    event.preventDefault();
                    move(dragged, order.indexOf(camera.id));
                    dragged = null;
                }
            });
            controls.append(handle);
            for (const direction of [-1, 1]) {
                const control = button(
                    `Move ${camera.name} ${direction < 0 ? "earlier" : "later"}`,
                    () =>
                        move(camera.id, order.indexOf(camera.id) + direction),
                    "secondary small icon-button",
                    direction < 0 ? "left" : "right",
                );
                control.dataset.move = direction;
                controls.append(control);
            }
            tile.append(controls);
        },
    };
}
