// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const paths = {
    popout: "M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5",
    dock: "M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-4M21 3 11 13m0-7v7h7",
    close: "m6 6 12 12M6 18 18 6",
    expand: "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5",
    collapse: "M3 8h5V3m8 0v5h5M8 21v-5H3m13 5v-5h5",
    preview:
        "M2 12C6 3 18 3 22 12 18 21 6 21 2 12ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
    hide: "m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.2A10 10 0 0 1 12 5c6 0 10 7 10 7a18 18 0 0 1-3 3.7M6.2 6.2A20 20 0 0 0 2 12s4 7 10 7a11 11 0 0 0 5.8-1.8",
    rename: "m14 5 5 5M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15l-1 5Z",
    chart: "M4 3v17h17M8 15v-3m5 3V6m5 9V9",
    logs: "M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 12h8m-8 4h8",
    add: "M12 5v14M5 12h14",
    remove: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    copy: "M8 8h13v13H8V8ZM16 8V3H3v13h5",
    reset: "M3 4v5h5M3.5 9a9 9 0 1 1 .5 7",
    layout: "M3 3h7v7H3V3Zm11 0h7v7h-7V3ZM3 14h7v7H3v-7Zm11 0h7v7h-7v-7Z",
    check: "m4 12 5 5L20 6",
    left: "m10 5-7 7 7 7M3 12h18",
    right: "m14 5 7 7-7 7M3 12h18",
};

// Keep the button and its handlers; only replace its visual label.
export function setIcon(button, name, label = button.textContent.trim()) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", paths[name]);
    svg.append(path);
    const text = document.createElement("span");
    text.textContent = label;
    if (button.classList.contains("icon-button")) {
        text.className = "sr-only";
        button.title = label;
    }
    button.replaceChildren(svg, text);
}
