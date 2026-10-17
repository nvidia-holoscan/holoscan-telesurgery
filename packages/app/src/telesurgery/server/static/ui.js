// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { setIcon } from "./icons.js";

export const $ = (selector) => document.querySelector(selector);
export function hasSelection(node) {
    const selection = node.ownerDocument.getSelection();
    return (
        selection &&
        !selection.isCollapsed &&
        (node.contains(selection.anchorNode) ||
            node.contains(selection.focusNode))
    );
}
export const codecName = (codec) =>
    ({
        h264: "H.264",
        h265: "H.265",
        nvjpeg: "nvJPEG",
        "raw-bgr8": "Uncompressed",
        "surgical-tokenizer": "Surgical Neural Tokenizer (trial)",
    })[codec || "h264"] || codec;
export const browserCamera = (camera) =>
    !camera.codec || ["h264", "surgical-tokenizer"].includes(camera.codec);
let toast;
export function element(tag, text, className = "") {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    node.className = className;
    return node;
}
export function button(text, action, className = "secondary small", icon) {
    const node = element("button", text, className);
    node.type = "button";
    if (icon) setIcon(node, icon, text);
    node.addEventListener("click", () =>
        Promise.resolve().then(action).catch(notice),
    );
    return node;
}
export function dismissOnBackdrop(dialog) {
    let pressedOutside = false;
    const outside = (event) => {
        const box = dialog.getBoundingClientRect();
        return (
            event.target === dialog &&
            (event.clientX < box.left ||
                event.clientX > box.right ||
                event.clientY < box.top ||
                event.clientY > box.bottom)
        );
    };
    dialog.addEventListener("pointerdown", (event) => {
        pressedOutside = outside(event);
    });
    dialog.addEventListener("click", (event) => {
        if (pressedOutside && outside(event)) dialog.close();
        pressedOutside = false;
    });
}
let confirmation;
export function confirmAction(title, detail, label = "Continue") {
    if (confirmation) return Promise.resolve(false);
    const previous = document.activeElement;
    const dialog = element("dialog", undefined, "confirm-action");
    confirmation = dialog;
    const heading = element("h2", title);
    heading.id = "confirm-action-title";
    dialog.setAttribute("aria-labelledby", heading.id);
    const description = element("p", detail);
    description.id = "confirm-action-detail";
    dialog.setAttribute("aria-describedby", description.id);
    const cancel = button("Cancel", () => dialog.close("cancel"));
    const accept = button(label, () => dialog.close("confirm"), "danger");
    const actions = element("div", undefined, "actions");
    actions.append(cancel, accept);
    dialog.append(heading, description, actions);
    document.body.append(dialog);
    return new Promise(resolve => {
        dialog.addEventListener("close", () => {
            confirmation = null;
            const accepted = dialog.returnValue === "confirm";
            dialog.remove();
            previous?.focus();
            resolve(accepted);
        }, {once: true});
        dialog.showModal();
        cancel.focus();
    });
}
export function notice(error) {
    $("#notice").textContent = error.message || String(error);
    $("#notice").hidden = false;
    clearTimeout(toast);
    toast = setTimeout(() => {
        $("#notice").hidden = true;
    }, 7000);
}
export async function api(path, body) {
    const response = await fetch(
        path,
        body === undefined
            ? {}
            : {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(body),
              },
    );
    if (response.status === 401) {
        location.reload();
        throw new Error("Dashboard access code required");
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
}
export async function action(name, params = {}) {
    return (await api("/api/action", { action: name, params })).result;
}
export function device(title, detail, status) {
    const card = element("div", undefined, "device");
    card.append(element("strong", title), element("small", detail));
    if (status) card.append(element("p", status, `status ${status}`));
    return card;
}
