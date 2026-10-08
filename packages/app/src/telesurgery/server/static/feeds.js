// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, element, button, browserCamera, codecName } from "./ui.js";
import { icon } from "./icons.js";

// Common viewing actions stay beside the video, without a modal picker.
export function feedStrip(select, display, closeNative) {
    let signature;
    return {
        update(cameras, selected, nativeViews) {
            const key = JSON.stringify([
                cameras.map(({ id, name, status, codec }) => [
                    id,
                    name,
                    status,
                    codec,
                ]),
                selected,
                Object.entries(nativeViews).map(([id, view]) => [
                    id,
                    view.status,
                ]),
            ]);
            if (signature === key) return;
            signature = key;
            const strip = $("#quick-feeds");
            strip.replaceChildren();
            for (const camera of cameras) {
                const native = ["starting", "running"].includes(
                    nativeViews[camera.id]?.status,
                );
                const shown = native || selected.includes(camera.id);
                const control = button(
                    "",
                    () =>
                        native
                            ? closeNative(camera.id)
                            : browserCamera(camera)
                              ? select(camera.id, !shown)
                              : display(camera.id, true),
                    "feed-shortcut",
                );
                control.setAttribute("aria-pressed", String(shown));
                control.setAttribute(
                    "aria-label",
                    `${shown ? "Hide" : "Show"} ${camera.name}`,
                );
                control.title = `${shown ? "Hide" : "Show"} ${camera.name}${browserCamera(camera) ? "" : " in Holoviz"} · ${codecName(camera.codec)}`;
                control.append(
                    icon("camera"),
                    element("span", camera.name, "feed-identity"),
                    icon(shown ? "check" : "add"),
                );
                strip.append(control);
            }
        },
    };
}
