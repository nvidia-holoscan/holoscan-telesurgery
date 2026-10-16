// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Correlate actual displayed frames by RTP timestamp. Never use callback arrival time.
const keys = ["p50", "p95", "p99", "p99_9"];
const ranks = [0.5, 0.95, 0.99, 0.999];

export function pathReport(samples) {
    if (!samples.length) return {};
    const names = Object.keys(samples.at(-1).stages);
    const missing = names.filter(
        (name) => !Number.isFinite(samples.at(-1).stages[name]),
    );
    const valid = samples.filter((s) =>
        names.every((n) => Number.isFinite(s.stages[n])),
    );
    const result = {
        boundary: "display",
        count: valid.length,
        sampled: samples.length,
        missing,
        stages: {},
        total: {},
        unavailable_reason: samples.at(-1).unavailable_reason,
    };
    const total = (s) => names.reduce((sum, n) => sum + s.stages[n], 0);
    const decoded = samples
        .map((s) => s.stages.browser_decode_ms)
        .filter(Number.isFinite)
        .sort((a, b) => a - b);
    if (decoded.length) {
        result.decode = {};
        ranks.forEach((rank, i) => {
            const position = rank * (decoded.length - 1),
                low = Math.floor(position);
            result.decode[keys[i]] =
                decoded[low] +
                (decoded[Math.ceil(position)] - decoded[low]) *
                    (position - low);
        });
    }
    if (missing.length || !valid.length) {
        result.partial = {};
        for (const name of names) {
            const values = samples
                .map((s) => s.stages[name])
                .filter(Number.isFinite)
                .sort((a, b) => a - b);
            if (!values.length) continue;
            result.partial[name] = {};
            ranks.forEach((rank, i) => {
                const position = rank * (values.length - 1),
                    low = Math.floor(position);
                result.partial[name][keys[i]] =
                    values[low] +
                    (values[Math.ceil(position)] - values[low]) *
                        (position - low);
            });
        }
        return result;
    }
    valid.sort((a, b) => total(a) - total(b));
    names.forEach((n) => (result.stages[n] = {}));
    ranks.forEach((rank, i) => {
        const position = rank * (valid.length - 1),
            low = Math.floor(position),
            high = Math.ceil(position);
        const weight = position - low;
        result.total[keys[i]] = 0;
        names.forEach((name) => {
            const value =
                valid[low].stages[name] * (1 - weight) +
                valid[high].stages[name] * weight;
            result.stages[name][keys[i]] = value;
            result.total[keys[i]] += value;
        });
    });
    result.error_ms = Math.max(...valid.map((v) => v.error_ms || 0));
    return result;
}

export function displayedPath(frame, metadata, clock) {
    const valid = (value) =>
        Number.isFinite(value) && value >= 0 ? value : null;
    const decode = valid(metadata.processingDuration * 1000);
    const synchronized = Number.isFinite(clock?.offset) &&
        Number.isFinite(clock?.error) && clock.error >= 0;
    // Resolve the full browser hop; sub-ms network transit alone can be below
    // clock uncertainty. Decode is subtracted so the remaining stage never overlaps.
    const playback =
        synchronized && decode !== null
            ? metadata.expectedDisplayTime -
              (frame.at_ms - clock.offset) -
              decode
            : NaN;
    // A busy browser can have several milliseconds of clock uncertainty and
    // still resolve a much larger display delay. Report that uncertainty instead
    // of dropping every frame above an arbitrary one-millisecond cutoff.
    const resolved = synchronized && Number.isFinite(playback) && playback >= clock.error;
    return {
        stages: {
            ...frame.stages,
            browser_decode_ms: decode,
            browser_playout_ms: resolved ? playback : null,
        },
        unavailable_reason: resolved ? undefined
            : !synchronized ? "Waiting for browser clock synchronization."
            : decode === null ? "The browser is not providing per-frame decode timing."
            : !Number.isFinite(metadata.expectedDisplayTime) ? "The browser is not providing display timestamps."
            : "Browser timing uncertainty exceeds the remaining display delay.",
        error_ms:
            !Number.isFinite(frame.error_ms) || !synchronized
                ? null
                : frame.error_ms + clock.error,
    };
}

export function frameTiming(peer, video) {
    const channel = peer.createDataChannel("frame-timing", {
        ordered: false,
        maxRetransmits: 0,
    });
    const sent = new Map(),
        displayed = new Map(),
        probes = new Set(),
        history = new Map();
    let samples = [],
        clocks = [],
        active = false,
        callback,
        timer,
        started = 0,
        lastRead = 0;
    const send = (message) => {
        if (channel.readyState === "open" && channel.bufferedAmount < 16384)
            channel.send(JSON.stringify(message));
    };
    const bounded = (map, key, value) => {
        map.set(key, value);
        if (map.size > 180) map.delete(map.keys().next().value);
    };
    function pair(rtp) {
        const frame = sent.get(rtp),
            metadata = displayed.get(rtp);
        if (!frame || !metadata) return;
        sent.delete(rtp);
        displayed.delete(rtp);
        const now = performance.now();
        clocks = clocks.filter((c) => now - c.at < 15000);
        const clock = clocks.reduce(
            (best, c) => (!best || c.error < best.error ? c : best),
            null,
        );
        if (now - started < 2000) return;
        const sample = {
            ...displayedPath(frame, metadata, clock),
            at: now / 1000,
        };
        samples.push(sample);
        if (samples.length > 10000) samples.shift();
        const durations = Object.values(sample.stages);
        if (durations.every(Number.isFinite)) {
            const bucket = Math.floor(now / 5000);
            if (!history.has(bucket)) history.set(bucket, { values: [] });
            const values = history.get(bucket).values;
            if (values.length < 5000)
                values.push(durations.reduce((a, b) => a + b, 0));
            history.get(bucket).summary = null;
            if (history.size > 721) history.delete(history.keys().next().value);
        }
    }
    function tick() {
        if (!active) return;
        if (performance.now() - lastRead > 40000) return stop();
        send({ type: "watch", enabled: true });
        const t0 = performance.now();
        probes.add(t0);
        if (probes.size > 16) probes.delete(probes.values().next().value);
        send({ type: "clock", t0 });
    }
    function presented(_now, metadata) {
        if (!active) return;
        if (Number.isFinite(metadata.rtpTimestamp)) {
            bounded(displayed, metadata.rtpTimestamp, metadata);
            pair(metadata.rtpTimestamp);
        }
        callback = video.requestVideoFrameCallback(presented);
    }
    channel.onmessage = (event) => {
        if (!active) return;
        let value;
        try {
            value = JSON.parse(event.data);
        } catch {
            return;
        }
        if (value.type === "clock" && probes.delete(value.t0)) {
            const t3 = performance.now();
            const roundTrip = t3 - value.t0 - (value.t2 - value.t1);
            if (roundTrip >= 0 && [value.t1, value.t2].every(Number.isFinite)) {
                clocks.push({
                    offset: (value.t1 - value.t0 + (value.t2 - t3)) / 2,
                    error: roundTrip / 2 + 0.2,
                    at: t3,
                });
                if (clocks.length > 15) clocks.shift();
            }
        } else if (value.type === "frame" && Number.isFinite(value.rtp)) {
            bounded(sent, value.rtp, value);
            pair(value.rtp);
        }
    };
    channel.onopen = () => {
        if (active) tick();
    };
    function stop() {
        active = false;
        clearInterval(timer);
        if (callback !== undefined) video.cancelVideoFrameCallback(callback);
        send({ type: "watch", enabled: false });
        sent.clear();
        displayed.clear();
        probes.clear();
    }
    return {
        read() {
            lastRead = performance.now();
            if (!active && video.requestVideoFrameCallback) {
                active = true;
                started = lastRead;
                tick();
                timer = setInterval(tick, 1000);
                callback = video.requestVideoFrameCallback(presented);
            }
            const current = Math.floor(lastRead / 5000);
            const timeline = [];
            for (const [bucket, item] of history) {
                if (current - bucket > 720) {
                    history.delete(bucket);
                    continue;
                }
                if (!item.summary || bucket === current) {
                    item.values.sort((a, b) => a - b);
                    item.summary = { at: bucket * 5 };
                    ranks.forEach((rank, i) => {
                        const position = rank * (item.values.length - 1),
                            low = Math.floor(position);
                        item.summary[keys[i]] =
                            item.values[low] +
                            (item.values[Math.ceil(position)] -
                                item.values[low]) *
                                (position - low);
                    });
                }
                timeline.push(item.summary);
            }
            return {
                ...pathReport(samples),
                history: timeline,
                history_end: lastRead / 1000,
            };
        },
        reset() {
            samples = [];
            clocks = [];
            history.clear();
            started = performance.now();
            sent.clear();
            displayed.clear();
        },
        stop,
    };
}
