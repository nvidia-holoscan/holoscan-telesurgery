// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0

import { element, action, notice } from "./ui.js";

export function nativeDepthControls(camera, tile, display = {}) {
    if (!camera.depth) return;
    const tools = element("div", undefined, "depth-tools");
    const mode = document.createElement("select"),
        range = document.createElement("select");
    mode.setAttribute("aria-label", `${camera.name} depth display`);
    range.setAttribute("aria-label", `${camera.name} depth range`);
    for (const [value, label] of [
        ["color", "Color"],
        ["overlay", "Depth overlay"],
        ["depth", "Depth"],
        ["side", "Side by side"],
    ]) {
        const option = element("option", label);
        option.value = value;
        mode.append(option);
    }
    for (const value of [0.5, 2, 5]) {
        const option = element("option", `0–${value} m`);
        option.value = value;
        range.append(option);
    }
    mode.value = display.mode || "color";
    range.value = display.distance || 2;
    mode.onchange = range.onchange = async () => {
        try {
            await action("view.depth", {
                camera: camera.id,
                mode: mode.value,
                distance: Number(range.value),
            });
        } catch (error) {
            notice(error);
        }
    };
    tools.append(mode, range);
    tile.append(tools);
}

// Present matching color/depth pairs together; late depth must not flash blank
// or be drawn over a newer color frame. Retain compressed depth across video jitter;
// decompress only matched pairs and keep at most three pending color snapshots.
export function depthView(peer, video, stage, caption, camera, display = {}) {
    if (!camera.depth) return { stop() {} };
    const channel = peer.createDataChannel("depth", {
        ordered: false,
        maxRetransmits: 0,
    });
    channel.binaryType = "arraybuffer";
    const canvas = document.createElement("canvas"),
        context = canvas.getContext("2d"),
        color = element("canvas", undefined, "depth-color"),
        colorContext = color.getContext("2d");
    canvas.hidden = color.hidden = true;
    stage.append(color, canvas);
    const tools = element("div", undefined, "depth-tools");
    function select(label, choices) {
        const control = document.createElement("select");
        control.setAttribute("aria-label", label);
        for (const [value, title] of choices) {
            const option = element("option", title);
            option.value = value;
            control.append(option);
        }
        return control;
    }
    const mode = select("Depth display", [
        ["color", "Color"],
        ["overlay", "Depth overlay"],
        ["depth", "Depth"],
        ["side", "Side by side"],
    ]);
    const range = select(
        "Depth range",
        [0.5, 2, 5].map((v) => [v, `0–${v} m`]),
    );
    mode.value = display.mode || "color";
    range.value = display.distance || (camera.name.includes("405") ? "0.5" : "2");
    const opacity = document.createElement("input");
    Object.assign(opacity, {
        type: "range",
        min: "0.1",
        max: "0.8",
        step: "0.05",
        value: String(display.opacity ?? 0.4),
    });
    opacity.setAttribute("aria-label", "Depth overlay opacity");
    const reading = element("output", "", "depth-reading");
    const legend = element("span", "Near → Far", "depth-legend");
    tools.append(mode, range, opacity, legend, reading);
    caption.append(tools);
    const chunks = new Map(),
        frames = new Map(),
        colors = new Map();
    let current,
        callback,
        point,
        lastPaint = 0,
        sequence = 0,
        displayed = 0,
        generation = 0,
        pending,
        stopped = false,
        inflating = false;
    const watching = () => !stopped && mode.value !== "color";
    const remove = (map, key) => {
        map.get(key)?.image?.close();
        map.delete(key);
    };
    const bounded = (map, key, value, limit = 3) => {
        remove(map, key);
        map.set(key, value);
        if (map.size > limit) remove(map, map.keys().next().value);
    };
    function unavailable() {
        current = undefined;
        color.hidden = true;
        context.clearRect(0, 0, canvas.width, canvas.height);
        reading.textContent = "Depth unavailable for this frame";
    }
    function paint() {
        if (!watching()) return;
        if (!current || performance.now() - lastPaint > 500) return unavailable();
        const { width, height, values } = current;
        if (canvas.width !== width) canvas.width = width;
        if (canvas.height !== height) canvas.height = height;
        const image = context.createImageData(width, height),
            limit = Number(range.value);
        const alpha =
            mode.value === "overlay"
                ? Math.round(Number(opacity.value) * 255)
                : 255;
        for (let i = 0; i < values.length; i++) {
            const value = values[i];
            if (!Number.isFinite(value) || value <= 0) continue;
            const t = Math.min(1, value / limit),
                j = i * 4;
            image.data[j] = Math.round(255 - 215 * t);
            image.data[j + 1] = Math.round(160 - 80 * t);
            image.data[j + 2] = Math.round(20 + 190 * t);
            image.data[j + 3] = alpha;
        }
        context.putImageData(image, 0, 0);
        const label =
            camera.depth_source === "simulated"
                ? "Simulated depth"
                : "Measured depth";
        reading.textContent = `${label} · click a surface`;
        if (point) {
            const x = Math.min(width - 1, Math.floor(point.x * width)),
                y = Math.min(height - 1, Math.floor(point.y * height));
            const z = values[y * width + x];
            reading.textContent =
                Number.isFinite(z) && z > 0
                    ? `${label}: ${(z * 1000).toFixed(1)} mm`
                    : "No valid depth at this point";
            context.strokeStyle = "white";
            context.lineWidth = Math.max(2, width / 600);
            context.beginPath();
            context.arc(x, y, width / 120, 0, 2 * Math.PI);
            context.stroke();
        }
    }
    function match(rtp) {
        const packet = frames.get(rtp), snapshot = colors.get(rtp);
        if (!packet || !snapshot) return;
        frames.delete(rtp);
        colors.delete(rtp);
        if (snapshot.sequence <= displayed || performance.now() - snapshot.at > 500 ||
            (pending && snapshot.sequence <= pending.snapshot.sequence)) {
            snapshot.image.close();
            return;
        }
        packet.snapshot = snapshot;
        if (inflating) {
            pending?.snapshot.image.close();
            pending = packet;
        } else decompress(packet);
    }
    function presented(now, metadata) {
        if (!watching()) return;
        callback = video.requestVideoFrameCallback(presented);
        if (video.readyState >= 2 && metadata.rtpTimestamp !== undefined) {
            let image;
            try {
                image = new VideoFrame(video, { timestamp: metadata.mediaTime * 1e6 });
            } catch (error) {
                // A stream can replace its decoded frame during startup/reconfiguration.
                if (error.name === "InvalidStateError") return;
                throw error;
            }
            bounded(colors, metadata.rtpTimestamp, {
                image,
                at: now,
                sequence: ++sequence,
            });
            match(metadata.rtpTimestamp);
        }
    }
    async function inflate(packet, version) {
        const stream = new Blob(packet.parts)
            .stream()
            .pipeThrough(new DecompressionStream("deflate"));
        const reader = stream.getReader(),
            expected = packet.width * packet.height * 4;
        const buffer = new Uint8Array(expected);
        let offset = 0;
        try {
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                if (offset + value.length > expected)
                    throw new Error("Invalid depth size");
                buffer.set(value, offset);
                offset += value.length;
            }
            if (offset !== expected) throw new Error("Truncated depth");
        } finally {
            await reader.cancel();
        }
        if (!watching() || version !== generation) return;
        const snapshot = packet.snapshot;
        if (snapshot.sequence <= displayed || performance.now() - snapshot.at > 500) return;
        const frame = {
            width: packet.width,
            height: packet.height,
            values: new Float32Array(buffer.buffer),
        };
        if (color.width !== frame.width) color.width = frame.width;
        if (color.height !== frame.height) color.height = frame.height;
        colorContext.drawImage(snapshot.image, 0, 0, frame.width, frame.height);
        current = frame;
        displayed = snapshot.sequence;
        lastPaint = snapshot.at;
        color.hidden = mode.value === "depth";
        paint();
        for (const [key, value] of colors) {
            if (value.sequence <= displayed) {
                remove(colors, key);
                frames.delete(key);
            }
        }
    }
    function decompress(packet) {
        const version = generation;
        inflating = true;
        inflate(packet, version)
            .catch(() => {}) // A bad frame cannot invalidate another matched pair.
            .finally(() => {
                packet.snapshot.image.close();
                inflating = false;
                if (pending && watching()) {
                    const next = pending;
                    pending = undefined;
                    decompress(next);
                }
            });
    }
    channel.onmessage = ({ data }) => {
        if (
            !watching() ||
            !(data instanceof ArrayBuffer) ||
            data.byteLength <= 12 ||
            data.byteLength > 49164
        )
            return;
        const view = new DataView(data),
            rtp = view.getUint32(0),
            width = view.getUint16(4),
            height = view.getUint16(6),
            index = view.getUint16(8),
            count = view.getUint16(10);
        if (
            !width ||
            width > 4096 ||
            !height ||
            height > 2160 ||
            !count ||
            count > 171 ||
            index >= count
        )
            return;
        let packet = chunks.get(rtp);
        if (!packet) {
            packet = {
                rtp,
                width,
                height,
                parts: new Array(count),
                received: 0,
            };
            bounded(chunks, rtp, packet);
        }
        if (
            packet.width !== width ||
            packet.height !== height ||
            packet.parts.length !== count ||
            packet.parts[index]
        )
            return;
        packet.parts[index] = data.slice(12);
        packet.received++;
        if (packet.received === count) {
            chunks.delete(rtp);
            packet.at = performance.now();
            packet.bytes = packet.parts.reduce((n, part) => n + part.byteLength, 0);
            bounded(frames, rtp, packet, 32);
            let bytes = [...frames.values()].reduce((n, value) => n + value.bytes, 0);
            for (const [key, value] of frames) {
                if (packet.at - value.at > 500 || bytes > 16 * 1024 * 1024) {
                    bytes -= value.bytes;
                    frames.delete(key);
                }
            }
            match(rtp);
        }
    };
    const send = () => {
        if (channel.readyState === "open")
            channel.send(JSON.stringify({ enabled: watching() }));
    };
    channel.onopen = send;
    function clear() {
        generation++;
        pending?.snapshot.image.close();
        pending = current = undefined;
        frames.clear();
        chunks.clear();
        for (const key of colors.keys()) remove(colors, key);
        color.hidden = true;
    }
    function update() {
        if (callback !== undefined) video.cancelVideoFrameCallback(callback);
        stage.dataset.depth = mode.value;
        canvas.hidden = !watching();
        range.hidden = legend.hidden = reading.hidden = !watching();
        opacity.hidden = mode.value !== "overlay";
        clear();
        if (watching()) {
            unavailable();
            callback = video.requestVideoFrameCallback(presented);
        }
        send();
    }
    const saveDisplay = () => action("view.depth", {
        camera: camera.id, mode: mode.value, distance: Number(range.value), opacity: Number(opacity.value),
    }).catch(notice);
    mode.onchange = () => { update(); saveDisplay(); };
    range.onchange = () => { paint(); saveDisplay(); };
    opacity.oninput = paint;
    opacity.onchange = saveDisplay;
    canvas.onclick = (event) => {
        const box = canvas.getBoundingClientRect();
        point = {
            x: (event.clientX - box.left) / box.width,
            y: (event.clientY - box.top) / box.height,
        };
        paint();
    };
    const timer = setInterval(() => {
        if (watching() && current && performance.now() - lastPaint > 500) unavailable();
    }, 100);
    update();
    return {
        stop() {
            stopped = true;
            clearInterval(timer);
            if (callback !== undefined)
                video.cancelVideoFrameCallback(callback);
            clear();
            send();
        },
    };
}
