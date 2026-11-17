// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { element, button, action, notice } from "./ui.js";

// A priority area is one polygon in picture coordinates (0-1). The patient's encoder
// concentrates quality inside it for every viewer; this page only draws and shows it.
const SVG = "http://www.w3.org/2000/svg";
const MAX_POINTS = 64;
const MIN_SHARE = 0.005;
const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
const round = (value) => Math.round(value * 10000) / 10000;

function distance(point, start, end) {
    const dx = end[0] - start[0], dy = end[1] - start[1];
    const length = dx * dx + dy * dy;
    const t = length ? clamp(((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length, 0, 1) : 0;
    return Math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy);
}
// Ramer-Douglas-Peucker: keep the points that carry the shape.
function reduce(points, tolerance) {
    if (points.length < 3) return points;
    const keep = new Uint8Array(points.length);
    keep[0] = keep[points.length - 1] = 1;
    const spans = [[0, points.length - 1]];
    while (spans.length) {
        const [first, last] = spans.pop();
        let index = -1, farthest = tolerance;
        for (let i = first + 1; i < last; i++) {
            const d = distance(points[i], points[first], points[last]);
            if (d > farthest) { farthest = d; index = i; }
        }
        if (index > 0) { keep[index] = 1; spans.push([first, index], [index, last]); }
    }
    return points.filter((_, i) => keep[i]);
}
// A freehand stroke as a closed outline of at most `limit` points.
export function outline(points, limit = MAX_POINTS) {
    let tolerance = 0.002, result = reduce(points, tolerance);
    while (result.length > limit) result = reduce(points, tolerance *= 1.5);
    return result.map(([x, y]) => [round(x), round(y)]);
}
function extent(points) {
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    return (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys));
}
const who = (camera) => camera.region_by ? ` set by ${camera.region_by}` : "";
const allowed = (state) => state.role === "patient" || Boolean(state.session?.robot);

// native: the tools sit on a card, not over a picture. changed: told the armed tool after each draw.
export function priorityArea(camera, { viewport, stage, surface, caption, native = false, changed }) {
    let current = camera, permitted = false, mode = null, gesture = null, pending, busy = false;
    const overlay = document.createElementNS(SVG, "svg");
    overlay.setAttribute("class", "region-overlay");
    overlay.setAttribute("viewBox", "0 0 1 1");
    overlay.setAttribute("preserveAspectRatio", "none");
    overlay.setAttribute("aria-hidden", "true");
    overlay.setAttribute("focusable", "false");
    const shapes = ["region-halo", "region-line"].map(name => {
        const shape = document.createElementNS(SVG, "polygon");
        shape.setAttribute("class", name);
        overlay.append(shape);
        return shape;
    });
    stage.append(overlay);

    const tools = element("div", undefined, `view-region${native ? " native-region" : ""}`);
    tools.setAttribute("role", "group");
    tools.setAttribute("aria-label", `${camera.name} priority area`);
    const label = element("span", "Priority area", "region-label");
    const arm = (name) => () => {
        mode = mode === name ? null : name;
        gesture = null;
        if (mode) {
            // Only one drag tool owns the picture at a time.
            viewport.dispatchEvent(new CustomEvent("view-tool", { detail: "region" }));
            viewport.focus({ preventScroll: true });
        }
        draw();
    };
    const box = button("Draw a box", arm("box"), "region-tool icon-button", "area-box");
    const lasso = button("Draw freehand", arm("lasso"), "region-tool icon-button", "area-lasso");
    const clear = button("Clear priority area", () => save(null), "region-tool icon-button", "area-clear");
    tools.append(label, box, lasso, clear);
    surface.append(tools);
    const instruction = element("div", "", "zoom-instruction region-instruction");
    instruction.hidden = true;
    viewport.append(instruction);
    const status = element("p", "", "region-status");
    status.setAttribute("role", "status");
    status.hidden = true;
    caption.append(status);

    function points() {
        if (gesture) {
            const { start, last, path } = gesture;
            return mode === "box"
                ? [start, [last[0], start[1]], last, [start[0], last[1]]]
                : path;
        }
        return pending === undefined ? current.region : pending;
    }
    function draw() {
        const supported = Boolean(current.region_supported);
        const reason = !supported ? "" : !permitted
            ? "View-only access cannot change the priority area"
            : current.region_unavailable
              ? `Priority area unavailable: ${current.region_unavailable}`
              : "";
        if (reason || !supported) mode = gesture = null;
        const shape = supported ? points() : null;
        for (const item of shapes)
            item.setAttribute("points", (shape || []).map(p => p.join(",")).join(" "));
        overlay.dataset.state = gesture ? "drawing" : pending !== undefined ? "saving" : "active";
        overlay.toggleAttribute("hidden", !shape?.length);
        tools.hidden = !supported;
        for (const [control, name, text] of [[box, "box", "Draw a box"], [lasso, "lasso", "Draw freehand"]]) {
            control.disabled = Boolean(reason) || busy;
            control.setAttribute("aria-pressed", String(mode === name));
            control.title = reason || `${text} around the priority area`;
        }
        clear.disabled = !permitted || busy || !current.region;
        clear.title = permitted ? "Clear priority area" : reason;
        if (mode) viewport.dataset.region = mode;
        else delete viewport.dataset.region;
        instruction.hidden = !mode;
        instruction.textContent = mode === "box"
            ? "Drag a box around the area · Esc to cancel"
            : "Draw around the area · Esc to cancel";
        const text = !supported ? ""
            : current.region ? `Priority area${who(current)}: picture detail is concentrated inside the outline.`
            : current.region_unavailable ? `Priority area unavailable: ${current.region_unavailable}.`
            : "";
        if (status.textContent !== text) status.textContent = text;
        status.hidden = !text;
        changed?.(mode);
    }
    async function save(shape) {
        if (busy) return;
        busy = true;
        pending = shape;
        draw();
        try {
            const result = await action("camera.region", { id: camera.id, points: shape });
            current = { ...current, ...result };
        } catch (error) {
            notice(error);
        } finally {
            busy = false;
            pending = undefined;
            draw();
        }
    }
    function locate(event) {
        const frame = overlay.getBoundingClientRect();
        return [
            clamp((event.clientX - frame.left) / frame.width, 0, 1),
            clamp((event.clientY - frame.top) / frame.height, 0, 1),
        ];
    }
    function cancel() {
        const tool = mode;
        mode = gesture = null;
        draw();
        return tool;
    }
    function down(event) {
        if (!mode || gesture || event.button !== 0) return;
        overlay.removeAttribute("hidden");
        const start = locate(event);
        gesture = { pointer: event.pointerId, start, last: start, path: [start], moved: false };
        // Keep the stroke when the pointer leaves the picture; a pointer the browser no
        // longer tracks cannot be captured and simply ends at the edge.
        try { viewport.setPointerCapture(event.pointerId); } catch { /* not capturable */ }
        viewport.focus({ preventScroll: true });
        event.preventDefault();
        event.stopImmediatePropagation();
        draw();
    }
    function move(event) {
        if (!gesture || event.pointerId !== gesture.pointer) return;
        const point = locate(event), frame = overlay.getBoundingClientRect();
        const previous = gesture.path[gesture.path.length - 1];
        if (Math.hypot((point[0] - previous[0]) * frame.width, (point[1] - previous[1]) * frame.height) >= 2) {
            gesture.path.push(point);
            gesture.moved = true;
        }
        gesture.last = point;
        event.stopImmediatePropagation();
        draw();
    }
    function up(event) {
        if (!gesture || event.pointerId !== gesture.pointer) return;
        event.stopImmediatePropagation();
        if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
        const drawn = points(), moved = gesture.moved, tool = mode;
        gesture = null;
        if (event.type === "pointercancel" || !moved) return draw();
        const shape = tool === "box" ? drawn.map(([x, y]) => [round(x), round(y)]) : outline(drawn);
        if (shape.length < 3 || extent(shape) < MIN_SHARE) {
            draw();
            return notice("Draw a larger priority area");
        }
        mode = null;
        save(shape);
    }
    // Capture so an armed tool, not view pan or zoom selection, receives the drag.
    const listeners = [
        [viewport, "pointerdown", down, true],
        [viewport, "pointermove", move, true],
        [viewport, "pointerup", up, true],
        [viewport, "pointercancel", up, true],
        [viewport, "dblclick", event => { if (mode) event.stopImmediatePropagation(); }, true],
        [viewport, "view-tool", event => { if (event.detail !== "region" && mode) cancel(); }, false],
        [surface, "keydown", event => {
            if (event.key !== "Escape" || !(mode || gesture)) return;
            const tool = cancel();
            (tool === "lasso" ? lasso : box).focus();
            event.preventDefault();
            event.stopPropagation();
        }, true],
    ];
    for (const [target, name, callback, capture] of listeners) target.addEventListener(name, callback, capture);
    // The outline keeps a constant width on screen while the view is zoomed.
    const scale = () => {
        const width = stage.clientWidth;
        overlay.style.setProperty(
            "--region-scale", String(width ? stage.getBoundingClientRect().width / width || 1 : 1),
        );
    };
    const watch = new MutationObserver(scale);
    watch.observe(stage, { attributes: true, attributeFilter: ["style", "data-depth"] });
    const resize = new ResizeObserver(scale);
    resize.observe(stage);
    draw();
    return {
        // Called with each status refresh; a request in flight keeps its own picture.
        update(camera, state) {
            permitted = allowed(state);
            if (!busy) current = camera;
            draw();
        },
        // Put the drawing tool down, as Esc does.
        cancel,
        stop() {
            watch.disconnect();
            resize.disconnect();
            for (const [target, name, callback, capture] of listeners) target.removeEventListener(name, callback, capture);
            delete viewport.dataset.region;
        },
    };
}

// A camera shown in Holoviz has no picture here. Its card gets the same tools; choosing a
// drawing tool opens a still picture lent by the Holoviz window, refreshed while it is open.
const STILL_MS = 350;
export function nativePriorityArea(camera) {
    let shown = false, timer;
    const root = element("div", undefined, "region-native");
    const viewport = element("div", undefined, "region-still");
    viewport.tabIndex = 0;
    viewport.hidden = true;
    viewport.setAttribute("role", "group");
    viewport.setAttribute("aria-label", `${camera.name} still picture for drawing a priority area`);
    const stage = element("div", undefined, "region-still-stage");
    const image = document.createElement("img");
    image.alt = `${camera.name}, still picture from Holoviz`;
    image.draggable = false;
    stage.append(image, element("p", "Waiting for the picture from Holoviz…", "region-still-waiting"));
    viewport.append(stage);
    // An armed tool would reopen the picture at the next status refresh: put it down too.
    const hide = button("Hide picture", () => { area.cancel(); open(false); }, "text-link region-still-hide");
    hide.hidden = true;

    const next = (delay) => {
        clearTimeout(timer);
        if (shown && !document.hidden) timer = setTimeout(load, delay);
    };
    function load() {
        image.src = `/api/cameras/${encodeURIComponent(camera.id)}/native-preview?t=${Date.now()}`;
    }
    image.addEventListener("load", () => { stage.dataset.ready = "true"; next(STILL_MS); });
    image.addEventListener("error", () => next(STILL_MS * 2));
    const resume = () => next(0);
    document.addEventListener("visibilitychange", resume);
    function open(value) {
        if (shown === value) return;
        shown = value;
        viewport.hidden = hide.hidden = !value;
        clearTimeout(timer);
        if (value) load();
        else {
            delete stage.dataset.ready;
            image.removeAttribute("src");
        }
    }
    const area = priorityArea(camera, {
        viewport, stage, surface: root, caption: root, native: true,
        changed: (mode) => { if (mode) open(true); },
    });
    // priorityArea added the tools and the status line; the picture belongs between them.
    root.insertBefore(viewport, root.querySelector(".region-status"));
    root.insertBefore(hide, root.querySelector(".region-status"));
    return {
        element: root,
        update(camera, state) {
            root.hidden = !camera.region_supported;
            if (root.hidden) open(false);
            // The still is stretched to the camera's shape, whatever size Holoviz lends.
            if (camera.width > 0 && camera.height > 0)
                stage.style.aspectRatio = `${camera.width} / ${camera.height}`;
            area.update(camera, state);
        },
        stop() {
            open(false);
            document.removeEventListener("visibilitychange", resume);
            area.stop();
        },
    };
}
