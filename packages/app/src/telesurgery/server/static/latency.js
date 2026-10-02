// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Read metrics only while the metrics view is visible. All histories are bounded.
async function browserTiming(peer, previous) {
    const report = await peer.getStats();
    const inbound = [...report.values()].find(
        (item) => item.type === "inbound-rtp" && item.kind === "video",
    );
    if (!inbound) return { detail: "Waiting for browser statistics" };
    const stored = previous.get(peer);
    const last = stored?.last;
    const continuous =
        last?.id === inbound.id &&
        !(inbound.framesDecoded < last.framesDecoded);
    const baseline = continuous ? stored.baseline : inbound;
    previous.set(peer, { last: inbound, baseline });
    const delta = (key) => (continuous ? inbound[key] - last[key] : NaN);
    const average = (total, count) =>
        delta(count) > 0 && delta(total) >= 0
            ? (1000 * delta(total)) / delta(count)
            : NaN;
    const since = (key) => Math.max(0, inbound[key] - baseline[key]);
    const seconds = delta("timestamp") / 1000;
    const transport = report.get(inbound.transportId);
    const pair = report.get(transport?.selectedCandidatePairId);
    return {
        detail:
            seconds > 0
                ? `Last ${seconds.toFixed(1)} seconds`
                : "Collecting interval statistics…",
        fps:
            seconds > 0 && delta("framesDecoded") >= 0
                ? delta("framesDecoded") / seconds
                : NaN,
        buffer: average("jitterBufferDelay", "jitterBufferEmittedCount"),
        decode: average("totalDecodeTime", "framesDecoded"),
        rtt: pair?.currentRoundTripTime * 1000,
        dropped: since("framesDropped"),
        lost: since("packetsLost"),
        freezes: since("freezeCount"),
    };
}

function append(history, value) {
    history.push(value);
    if (history.length > 60) history.shift();
}

export function latencyReader(tiles, device = null) {
    const browsers = new WeakMap(),
        arrivals = new Map(),
        histories = new Map(),
        watched = new Set();
    const read = async (signal) => {
        const response = await fetch(
            `/api/status?metrics=1${device ? `&device=${encodeURIComponent(device)}` : ""}`,
            { signal },
        );
        if (!response.ok)
            throw new Error(`Cannot load metrics: ${response.statusText}`);
        const state = await response.json();
        const patient = state.role === "patient";
        const inventory = patient ? state : state.session || {};
        const cameras = (inventory.cameras || []).filter(
            (c) => !device || c.id === device,
        );
        state.metric_robots = (inventory.robots || []).filter(
            (r) => !device || r.id === device,
        );
        const at = performance.now();
        const streams = await Promise.all(
            (patient
                ? cameras.map((c) => c.id)
                : (state.selected || []).filter(
                      (id) => !device || id === device,
                  )
            ).map(async (id) => {
                const camera = cameras.find((item) => item.id === id);
                const raw = camera?.codec === "raw-bgr8";
                const native = state.native_views?.[id];
                const holoviz =
                    !patient &&
                    ["starting", "running"].includes(native?.status);
                const report =
                    (holoviz ? native.metrics : state.video?.[id]) || {};
                const key = `${state.session?.id}/${id}/${holoviz}`;
                const received = holoviz ? native.frames : report.frames;
                const last = arrivals.get(key);
                const seconds = last ? (at - last.at) / 1000 : NaN;
                const frames = last ? received - last.frames : NaN;
                const fps = frames >= 0 && seconds > 0 ? frames / seconds : NaN;
                let browser;
                let path = report.path || {};
                if (!holoviz && tiles.has(id)) {
                    try {
                        const timing = tiles.get(id).timing;
                        if (!patient && timing) {
                            if (!watched.has(timing)) {
                                watched.add(timing);
                            }
                            path = timing.read();
                        }
                        browser = await browserTiming(
                            tiles.get(id).peer,
                            browsers,
                        );
                    } catch {
                        browser = {
                            detail: "Browser statistics unavailable while reconnecting",
                        };
                    }
                }
                if (signal.aborted) return null;
                arrivals.set(key, { frames: received, at });
                const resolved = [
                    "Same host · monotonic clock",
                    "Synchronized UTC clocks",
                    "Relative clock estimate",
                ].includes(report.delivery_status);
                const history = histories.get(key) || [];
                append(history, {
                    at,
                    fps: patient || holoviz ? fps : browser?.fps,
                    delivery: path.total?.p99,
                    encode: report.steady_metrics?.[
                        raw ? "pack_ms" : "encode_ms"
                    ]?.p99,
                    decode: holoviz
                        ? report.steady_metrics?.[
                              raw ? "unpack_ms" : "decode_ms"
                          ]?.p99
                        : path.decode?.p99,
                });
                histories.set(key, history);
                return {
                    id,
                    name: camera?.name || id,
                    raw,
                    holoviz,
                    report,
                    path,
                    fps,
                    browser,
                    resolved,
                    history,
                };
            }),
        );
        if (signal.aborted) return null;
        // Prune cameras that are no longer viewed instead of retaining session history.
        const active = new Set(
            streams
                .filter(Boolean)
                .map(
                    (stream) =>
                        `${state.session?.id}/${stream.id}/${stream.holoviz}`,
                ),
        );
        for (const key of histories.keys()) {
            if (!active.has(key)) {
                histories.delete(key);
                arrivals.delete(key);
            }
        }
        return {
            state,
            streams: streams.filter(Boolean),
            status: `Updated ${new Date().toLocaleTimeString()} · Live while open`,
        };
    };
    read.close = (reset = false) => {
        for (const timing of watched) {
            timing.stop();
            if (reset) timing.reset();
        }
        watched.clear();
    };
    return read;
}
