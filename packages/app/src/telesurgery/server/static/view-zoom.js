// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

import { element, button, action, notice } from "./ui.js";

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const label = (v) => `${Number(v.toFixed(2))}×`;
const preferences = new Map();

// Only metadata crosses the local API. At most one request is in flight; drag
// events replace the pending update rather than building a queue of old views.
function sender(send, delay = 60) {
    let pending, running = false, timer;
    async function flush() {
        clearTimeout(timer);
        if (running || !pending) return;
        const value = pending;
        pending = null;
        running = true;
        try { await send(value); }
        catch (error) { pending = null; notice(error); }
        finally {
            running = false;
            if (pending) timer = setTimeout(flush, delay);
        }
    }
    return {
        put(value) { pending = value; clearTimeout(timer); timer = setTimeout(flush, delay); },
        async flush() {
            await flush();
            while (running || pending) {
                await new Promise(resolve => setTimeout(resolve, 10));
                await flush();
            }
        },
        stop() { clearTimeout(timer); pending = null; },
    };
}

export function viewZoom(camera, { viewport, stage, surface, initial = {}, native = false } = {}) {
    let view = { scale: 1, x: 0.5, y: 0.5, ...initial, ...preferences.get(camera.id) };
    let selecting = false, gesture, suppressClick = false;
    const send = sender(value => action("view.zoom", { camera: camera.id, ...value }));
    const root = element("div", undefined, `view-zoom${native ? " native-zoom" : ""}`);
    root.setAttribute("role", "group");
    root.setAttribute("aria-label", `${camera.name} view zoom`);
    const details = element("div", undefined, "zoom-menu");
    const summary = button(label(view.scale), () => {
        if (panel.matches(":popover-open")) panel.hidePopover();
        else {
            panel.showPopover();
            positionMenu();
        }
    }, "zoom-level");
    summary.title = "Zoom controls";
    summary.setAttribute("aria-label", "Zoom controls");
    const panel = element("div", undefined, "zoom-panel");
    panel.popover = "auto";
    function positionMenu() {
        const box = root.getBoundingClientRect();
        const above = box.top - panel.offsetHeight - 8;
        panel.style.left = `${clamp(box.right - panel.offsetWidth, 8, innerWidth - panel.offsetWidth - 8)}px`;
        panel.style.top = `${clamp(above >= 8 ? above : box.bottom + 8, 8, innerHeight - panel.offsetHeight - 8)}px`;
    }
    let menuEvents;
    panel.addEventListener("toggle", event => {
        const open = event.newState === "open";
        summary.setAttribute("aria-expanded", String(open));
        menuEvents?.abort();
        if (open) {
            menuEvents = new AbortController();
            for (const type of ["resize", "scroll"])
                window.addEventListener(type, positionMenu, { passive: true, capture: true, signal: menuEvents.signal });
        }
    });
    const header = element("div", undefined, "zoom-heading");
    const reset = button("Reset", () => {
        selecting = false;
        selection?.setAttribute("hidden", "");
        update({ scale: 1, x: 0.5, y: 0.5 });
    }, "zoom-reset", "reset");
    header.append(element("strong", "View zoom"), reset);
    const range = document.createElement("input");
    Object.assign(range, { type: "range", min: "1", max: "4", step: "0.05", value: view.scale });
    range.setAttribute("aria-label", `${camera.name} zoom`);
    range.oninput = () => update({ scale: Number(range.value) });
    const ends = element("div", undefined, "zoom-range-labels");
    ends.append(element("span", "1×"), element("span", "4×"));
    panel.append(header, range, ends);
    let area;
    if (viewport) {
        area = button("Select area", () => {
            selecting = !selecting;
            panel.hidePopover();
            draw();
            viewport.focus({ preventScroll: true });
        }, "zoom-area", "select-area");
        panel.append(area, element("small", "Drag to pan · Double-click to reset", "zoom-help"));
    } else {
        const pan = element("div", undefined, "zoom-pan");
        pan.setAttribute("role", "group");
        pan.setAttribute("aria-label", "Pan view");
        pan.append(element("span", "Pan"));
        for (const [name, dx, dy] of [["left", -1, 0], ["up", 0, -1], ["down", 0, 1], ["right", 1, 0]]) {
            const control = button(`Pan ${name}`, () => update({
                x: view.x + dx * 0.1 / view.scale,
                y: view.y + dy * 0.1 / view.scale,
            }), "zoom-step icon-button", name);
            control.dataset.pan = "true";
            pan.append(control);
        }
        panel.append(pan, element("small", "Switch to browser to select an area.", "zoom-help"));
    }
    details.append(summary, panel);
    const minus = button("Zoom out", () => update({ scale: view.scale - 0.25 }), "zoom-step icon-button", "minus");
    const plus = button("Zoom in", () => update({ scale: view.scale + 0.25 }), "zoom-step icon-button", "add");
    root.append(minus, details, plus);
    const selection = viewport ? element("div", undefined, "zoom-selection") : null;
    const instruction = viewport ? element("div", "Drag an area · Esc to cancel", "zoom-instruction") : null;
    if (viewport) {
        selection.hidden = instruction.hidden = true;
        viewport.append(selection, instruction);
        surface.append(root);
        viewport.tabIndex = 0;
        viewport.setAttribute("aria-label", `${camera.name} video. Use zoom controls or select an area.`);
    }
    function dimensions() {
        const width = viewport.clientWidth, height = viewport.clientHeight;
        const aspect = camera.width / camera.height * (stage.dataset.depth === "side" ? 2 : 1);
        const w = Math.min(width, height * aspect), h = Math.min(height, width / aspect);
        return { width, height, w, h };
    }
    function draw() {
        summary.textContent = label(view.scale);
        summary.setAttribute("aria-label", `Zoom controls, ${label(view.scale)}`);
        range.value = view.scale;
        range.setAttribute("aria-valuetext", label(view.scale));
        minus.disabled = view.scale <= 1;
        plus.disabled = view.scale >= 4;
        root.dataset.zoomed = String(view.scale > 1);
        root.querySelectorAll("[data-pan]").forEach(b => { b.disabled = view.scale === 1; });
        if (!viewport) return;
        const aspect = camera.width / camera.height * (stage.dataset.depth === "side" ? 2 : 1);
        const fittedWidth = Math.min(surface.clientWidth, surface.clientHeight * aspect);
        viewport.style.width = `${fittedWidth}px`;
        viewport.style.height = `${fittedWidth / aspect}px`;
        const { width, height, w, h } = dimensions();
        if (!w || !h) return;
        const dx = Math.max(0, (w * view.scale - width) / 2);
        const dy = Math.max(0, (h * view.scale - height) / 2);
        const tx = clamp((0.5 - view.x) * w * view.scale, -dx, dx);
        const ty = clamp((0.5 - view.y) * h * view.scale, -dy, dy);
        stage.style.transform = view.scale === 1 ? "none" : `translate3d(${tx}px, ${ty}px, 0) scale(${view.scale})`;
        viewport.dataset.zoomed = String(view.scale > 1);
        viewport.dataset.selecting = String(selecting);
        instruction.hidden = !selecting;
        area.setAttribute("aria-pressed", String(selecting));
    }
    function update(values) {
        view = { ...view, ...values };
        view.scale = clamp(view.scale, 1, 4);
        const edge = 0.5 / view.scale;
        view.x = clamp(view.x, edge, 1 - edge);
        view.y = clamp(view.y, edge, 1 - edge);
        preferences.set(camera.id, { ...view });
        draw();
        send.put({ ...view });
    }
    root.addEventListener("keydown", event => {
        if (event.key === "Escape") { panel.hidePopover(); summary.focus(); event.stopPropagation(); }
    });
    root.addEventListener("focusout", event => {
        if (!root.contains(event.relatedTarget)) panel.hidePopover();
    });
    function point(event) {
        const box = viewport.getBoundingClientRect();
        return { x: clamp(event.clientX - box.left, 0, box.width), y: clamp(event.clientY - box.top, 0, box.height) };
    }
    function down(event) {
        if (event.button !== 0 || root.contains(event.target)) return;
        panel.hidePopover();
        if (!selecting && view.scale === 1) return;
        const p = point(event);
        gesture = { ...p, view: { ...view }, area: selecting, moved: false };
        viewport.setPointerCapture(event.pointerId);
        viewport.focus({ preventScroll: true });
        event.preventDefault();
    }
    function move(event) {
        if (!gesture) return;
        const p = point(event), dx = p.x - gesture.x, dy = p.y - gesture.y;
        gesture.moved ||= Math.hypot(dx, dy) > 4;
        if (gesture.area) {
            selection.hidden = false;
            Object.assign(selection.style, {
                left: `${Math.min(p.x, gesture.x)}px`, top: `${Math.min(p.y, gesture.y)}px`,
                width: `${Math.abs(dx)}px`, height: `${Math.abs(dy)}px`,
            });
        } else {
            const { w, h } = dimensions();
            update({ x: gesture.view.x - dx / (w * view.scale), y: gesture.view.y - dy / (h * view.scale) });
        }
    }
    function up(event) {
        if (!gesture) return;
        const start = gesture;
        gesture = null;
        suppressClick = start.moved;
        if (start.area && start.moved && event.type !== "pointercancel") {
            const p = point(event), { width, height, w, h } = dimensions();
            const cropW = Math.abs(p.x - start.x), cropH = Math.abs(p.y - start.y);
            if (cropW >= 8 && cropH >= 8) {
                const scale = clamp(start.view.scale * Math.min(w / cropW, h / cropH), 1, 4);
                update({ scale,
                    x: start.view.x + ((p.x + start.x) / 2 - width / 2) / (w * start.view.scale),
                    y: start.view.y + ((p.y + start.y) / 2 - height / 2) / (h * start.view.scale),
                });
            }
            selecting = false;
        }
        selection.hidden = true;
        draw();
        if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    }
    const listeners = [];
    function listen(name, callback, options) {
        viewport.addEventListener(name, callback, options);
        listeners.push([name, callback, options]);
    }
    let resize, modes;
    if (viewport) {
        listen("pointerdown", down);
        listen("pointermove", move);
        listen("pointerup", up);
        listen("pointercancel", up);
        listen("click", event => {
            if (suppressClick && !root.contains(event.target)) { event.stopImmediatePropagation(); suppressClick = false; }
        }, true);
        listen("dblclick", event => {
            if (!root.contains(event.target)) { event.preventDefault(); update({ scale: 1, x: 0.5, y: 0.5 }); }
        });
        listen("keydown", event => {
            if (root.contains(event.target)) return;
            if (event.key === "Escape" && selecting) {
                selecting = false; gesture = null; selection.hidden = true; draw();
                event.preventDefault(); event.stopPropagation();
            }
        });
        resize = new ResizeObserver(draw);
        resize.observe(surface);
        modes = new MutationObserver(draw);
        modes.observe(stage, { attributes: true, attributeFilter: ["data-depth"] });
    }
    draw();
    return {
        element: root,
        flush: () => send.flush(),
        stop() {
            resize?.disconnect(); modes?.disconnect(); menuEvents?.abort(); send.stop();
            for (const args of listeners) viewport.removeEventListener(...args);
        },
    };
}

export function cameraZoom(camera) {
    const control = camera.camera_zoom;
    if (!control) return null;
    const root = element("details", undefined, "camera-zoom");
    const summary = element("summary", "Camera zoom");
    const panel = element("div", undefined, "camera-zoom-panel");
    const range = document.createElement("input");
    Object.assign(range, { type: "range", min: control.min, max: control.max, step: control.step, value: control.value });
    range.setAttribute("aria-label", `${camera.name} camera zoom`);
    const value = element("output", String(control.value));
    value.title = "Camera-reported zoom value";
    let confirmed = control.value;
    const send = sender(async requested => {
        try {
            const result = await action("camera.zoom", { id: camera.id, value: requested.value });
            confirmed = result.value;
            if (Number(range.value) === requested.value) range.value = value.textContent = confirmed;
        } catch (error) {
            range.value = value.textContent = confirmed;
            throw error;
        }
    }, 150);
    function change() { value.textContent = range.value; send.put({ value: Number(range.value) }); }
    range.oninput = change;
    const reset = button("Reset", () => { range.value = control.default; change(); }, "secondary small", "reset");
    const ends = element("div", undefined, "zoom-range-labels");
    ends.append(element("span", "Wide"), element("span", "Tight"));
    const row = element("div", undefined, "camera-zoom-range");
    row.append(range, value, reset);
    panel.append(row, ends, element("small", "Changes the outgoing image for every viewer. Values use the camera’s own range."));
    root.append(summary, panel);
    return root;
}
