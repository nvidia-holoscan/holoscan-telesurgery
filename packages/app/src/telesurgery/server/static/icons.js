// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const paths = {
    camera: "M4 6h4l2-3h4l2 3h4v14H4V6Zm12 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
    server: "M4 3h16v7H4V3Zm0 11h16v7H4v-7ZM7 6h.01M7 17h.01M11 6h6m-6 11h6",
    robot: "M5 20h14M8 20v-4l5-4-5-4m8-5 4 4-4 4M8 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8Zm5 8 4 4v4M12 7h6",
    people: "M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3M13 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0m5 8a4 4 0 0 1 4 4v3M17 2a4 4 0 0 1 0 8",
    settings: "M4 7h16M4 17h16M8 4v6m8 4v6",
    appearance: "M21 12a9 9 0 1 0-9 9h1a2 2 0 0 0 0-4h-1a1.5 1.5 0 0 1 0-3h6a3 3 0 0 0 3-2ZM7 8h.01M11 5.5h.01M16 7h.01M5.5 12h.01",
    monitor: "M3 3h18v14H3V3Zm5 18h8m-4-4v4",
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
    minus: "M5 12h14",
    "select-area": "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M9 9h6v6H9V9Z",
    remove: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
    copy: "M8 8h13v13H8V8ZM16 8V3H3v13h5",
    reset: "M3 4v5h5M3.5 9a9 9 0 1 1 .5 7",
    replay: "M3 4v5h5M3.5 9a9 9 0 1 1 .5 7M10 8l6 4-6 4V8Z",
    home: "m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-8H9v8H4a1 1 0 0 1-1-1V10Z",
    stop: "M6 6h12v12H6V6Z",
    disconnect:
        "m19 5 3-3M2 22l3-3M7 12l5 5-3 3a2 2 0 0 1-3 0l-2-2a2 2 0 0 1 0-3l3-3Zm5-5 5 5 3-3a2 2 0 0 0 0-3l-2-2a2 2 0 0 0-3 0l-3 3ZM8.5 13.5l2-2m0 4.5 2-2",
    leave: "M9 4H4v16h5m-1-8h13m-5-5 5 5-5 5",
    layout: "M3 3h7v7H3V3Zm11 0h7v7h-7V3ZM3 14h7v7H3v-7Zm11 0h7v7h-7v-7Z",
    check: "m4 12 5 5L20 6",
    left: "m10 5-7 7 7 7M3 12h18",
    right: "m14 5 7 7-7 7M3 12h18",
    up: "m5 10 7-7 7 7M12 3v18",
    down: "m5 14 7 7 7-7M12 3v18",
    square: "M4 4h16v16H4V4Z",
    circle: "M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z",
    triangle: "M12 3 22 21H2L12 3Z",
};

export function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon");
    if (name === "stop") svg.classList.add("icon-stop");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", paths[name]);
    svg.append(path);
    return svg;
}

// The three positive robot axes, projected into the pen's right/forward/up frame.
export function axisTriad(basis) {
    const ns = "http://www.w3.org/2000/svg";
    const node = (tag, attributes) => {
        const element = document.createElementNS(ns, tag);
        for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
        return element;
    };
    const svg = node("svg", {class: "axis-triad", role: "img", focusable: "false"});
    const projection = [[1, 0], [0.72, -0.69], [0, -1]];
    const directions = [["right", "left"], ["forward", "back"], ["up", "down"]];
    const description = [], bounds = [[-4, -4], [4, 4]];
    for (const [index, axis] of ["X", "Y", "Z"].entries()) {
        const row = basis[index];
        if (!Array.isArray(row) || row.length !== 3 || !row.every(Number.isFinite)) continue;
        const penAxis = row?.findIndex(value => Math.abs(value) === 1);
        const projected = [0, 1].map(axis => row.reduce((sum, v, i) => sum + v * projection[i][axis], 0));
        const length = Math.hypot(...projected);
        if (length < 1e-6) continue;
        const [dx, dy] = projected.map(v => v / length);
        const x = dx * 34, y = dy * 34, tx = dx * 47, ty = dy * 47;
        const group = node("g", {"data-axis": axis});
        group.append(node("path", {d: `M0 0L${x} ${y}M${x - 6 * dx + 3 * dy} ${y - 6 * dy - 3 * dx}L${x} ${y}L${x - 6 * dx - 3 * dy} ${y - 6 * dy + 3 * dx}`}));
        const label = node("text", {x: tx, y: ty, "text-anchor": "middle", "dominant-baseline": "central"});
        label.textContent = `+${axis}`;
        group.append(label);
        svg.append(group);
        bounds.push([tx - 12, ty - 10], [tx + 12, ty + 10]);
        description.push(penAxis >= 0 && row.every((v, i) => i === penAxis || v === 0)
            ? `+${axis}: pen ${directions[penAxis][row[penAxis] > 0 ? 0 : 1]}`
            : `+${axis}: pen movement along its arrow`);
    }
    svg.append(node("circle", {cx: 0, cy: 0, r: 2.5}));
    const minX = Math.min(...bounds.map(p => p[0])), minY = Math.min(...bounds.map(p => p[1]));
    svg.setAttribute("viewBox", `${minX} ${minY} ${Math.max(...bounds.map(p => p[0])) - minX} ${Math.max(...bounds.map(p => p[1])) - minY}`);
    const text = `Pen movement directions. ${description.join("; ")}. Opposite movement decreases each coordinate. Fixed to the device frame.`;
    svg.setAttribute("aria-label", text);
    const title = node("title", {});
    title.textContent = text;
    svg.prepend(title);
    return svg;
}

// Generic pads retain positional labels for assistive text, while the diamond
// shows the physical button location without relying on a manufacturer's letters.
export function setControllerKey(key, label) {
    if (key.dataset.binding === label) return;
    key.dataset.binding = label;
    const positions = {North: [12, 5], South: [12, 19], West: [5, 12], East: [19, 12]};
    const symbol = {"←": "left", "→": "right", "□": "square", "○": "circle", "△": "triangle", "✕": "close"}[label];
    const text = document.createElement("span");
    text.textContent = label;
    if (positions[label]) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("class", "icon face-button-icon");
        svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("focusable", "false");
        for (const [position, [x, y]] of Object.entries(positions)) {
            const dot = document.createElementNS(svg.namespaceURI, "circle");
            dot.setAttribute("cx", x);
            dot.setAttribute("cy", y);
            dot.setAttribute("r", "3");
            dot.setAttribute("fill", position === label ? "currentColor" : "none");
            dot.setAttribute("opacity", position === label ? "1" : ".4");
            dot.dataset.position = position;
            svg.append(dot);
        }
        text.className = "sr-only";
        key.replaceChildren(svg, text);
    } else if (symbol) {
        text.className = "sr-only";
        key.replaceChildren(icon(symbol), text);
    } else {
        key.replaceChildren(text);
    }
}

// Keep the button and its handlers; only replace its visual label.
export function setIcon(button, name, label = button.textContent.trim()) {
    const text = document.createElement("span");
    text.textContent = label;
    if (button.classList.contains("icon-button")) {
        text.className = "sr-only";
        button.title = label;
    }
    button.replaceChildren(icon(name), text);
}
