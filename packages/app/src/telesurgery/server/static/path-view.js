// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// One column follows one total-latency percentile, so its contributions add up.
export const stages = {
    acquisition_ms: ["Frame preparation", "patient"],
    encoder_queue_ms: ["Processing queue", "patient"],
    encode_ms: ["Encode", "encode"],
    pack_ms: ["Pack", "patient"],
    source_relay_ms: ["Source relay", "patient"],
    source_queue_ms: ["Source queue", "patient"],
    send_queue_ms: ["Send queue", "patient"],
    transport_ms: ["Stream transport", "transport"],
    receiver_queue_ms: ["Receive queue", "surgeon"],
    decode_ms: ["Decode", "decode"],
    preview_encode_ms: ["Browser preview encode", "surgeon"],
    unpack_ms: ["Upload", "surgeon"],
    render_submit_ms: ["Holoviz handoff", "surgeon"],
    browser_queue_ms: ["WebRTC queue", "surgeon"],
    browser_decode_ms: ["Decode", "decode"],
    browser_playout_ms: ["WebRTC + display", "display"],
};
const quantiles = ["p50", "p95", "p99", "p99_9"];
const title = (key) => key.toUpperCase().replace("_", ".");
const node = (tag, text, className) => {
    const value = document.createElement(tag);
    value.textContent = text;
    if (className) value.className = className;
    return value;
};

export function pathView(root, path = {}) {
    historyView(
        root.querySelector(".latency-history"),
        path.history || [],
        path.history_end,
    );
    const names = Object.keys(stages).filter((name) => path.stages?.[name]);
    const groups = new Set(names.map((name) => `stage-${stages[name][1]}`));
    for (const item of root.querySelectorAll(".latency-legend span"))
        item.hidden = !groups.has(item.querySelector("i")?.className);
    const values = {};
    // Allocate rounding remainders so even the displayed hundredths add exactly.
    for (const q of quantiles) {
        const fractions = names
            .map((name) => {
                const value = path.stages[name][q] * 100;
                (values[name] ||= {})[q] = Math.floor(value);
                return { name, remainder: value - Math.floor(value) };
            })
            .sort((a, b) => b.remainder - a.remainder);
        const difference =
            Math.round((path.total?.[q] || 0) * 100) -
            names.reduce((sum, n) => sum + values[n][q], 0);
        fractions.slice(0, difference).forEach(({ name }) => values[name][q]++);
    }
    const chart = root.querySelector(".latency-bars");
    chart.replaceChildren();
    chart.hidden = !names.length;
    if (!names.length) {
        if (path.partial) {
            const body = root.querySelector("tbody");
            body.replaceChildren();
            for (const [name, [label]] of Object.entries(stages)) {
                if (!path.partial[name] && !path.missing?.includes(name))
                    continue;
                const row = document.createElement("tr"),
                    heading = node("th", label);
                heading.scope = "row";
                row.append(
                    heading,
                    ...quantiles.map((q) =>
                        node(
                            "td",
                            path.missing?.includes(name)
                                ? "—"
                                : path.partial[name][q].toFixed(2),
                        ),
                    ),
                );
                body.append(row);
            }
        }
        return false;
    }
    const max = Math.max(...quantiles.map((q) => path.total[q]), 0.001);
    for (const q of quantiles) {
        const row = node("div", "", "latency-bar-row");
        const bar = node("div", "", "latency-bar");
        const total = (Math.round(path.total[q] * 100) / 100).toFixed(2);
        row.append(
            node("strong", title(q)),
            bar,
            node("strong", `${total} ms`, "latency-bar-total"),
        );
        for (const name of names) {
            const [label, group] = stages[name];
            const segment = node("span", "", `latency-segment stage-${group}`);
            const text = `${label}: ${(values[name][q] / 100).toFixed(2)} ms`;
            segment.title = text;
            segment.setAttribute("aria-label", text);
            segment.style.width = `${(path.stages[name][q] / max) * 100}%`;
            bar.append(segment);
        }
        chart.append(row);
    }
    const tbody = root.querySelector("tbody");
    tbody.replaceChildren();
    for (const name of names) {
        const [label, group] = stages[name];
        const row = document.createElement("tr"),
            heading = node("th", "");
        heading.scope = "row";
        heading.append(
            node("span", "", `stage-dot stage-${group}`),
            document.createTextNode(label),
        );
        row.append(
            heading,
            ...quantiles.map((q) =>
                node("td", (values[name][q] / 100).toFixed(2)),
            ),
        );
        tbody.append(row);
    }
    const row = node("tr", "", "latency-total"),
        heading = node("th", "Total");
    heading.scope = "row";
    row.append(
        heading,
        ...quantiles.map((q) => node("td", path.total[q].toFixed(2))),
    );
    tbody.append(row);
    return true;
}

function historyView(root, history, end) {
    root.history = { history, end };
    const range = root.querySelector(".history-range");
    range.onchange = () =>
        historyView(root, root.history.history, root.history.end);
    const span = Number(range.value);
    end = end || history.at(-1)?.at || 0;
    const start = end - span;
    history = history.filter((point) => point.at >= start && point.at <= end);
    const svg = root.querySelector("svg");
    svg.replaceChildren();
    const label = root.querySelector("p");
    svg.toggleAttribute("hidden", history.length < 2);
    if (history.length < 2) {
        label.textContent = "History appears after two 5-second intervals.";
        return;
    }
    const make = (tag, attributes) => {
        const element = document.createElementNS(
            "http://www.w3.org/2000/svg",
            tag,
        );
        for (const [key, value] of Object.entries(attributes))
            element.setAttribute(key, value);
        return element;
    };
    const high = Math.max(...history.map((s) => s.p99_9), 0.01) * 1.1;
    const x = (at) => 40 + ((at - start) / (end - start)) * 548;
    const y = (value) => 128 - (value / high) * 114;
    for (const fraction of [0, 0.5, 1]) {
        const value = fraction * high;
        svg.append(
            make("line", {
                x1: 40,
                x2: 588,
                y1: y(value),
                y2: y(value),
                class: "history-grid",
            }),
        );
        const text = make("text", {
            x: 34,
            y: y(value) + 3,
            "text-anchor": "end",
        });
        text.textContent = value.toFixed(1);
        svg.append(text);
    }
    for (const key of quantiles) {
        let line = "",
            previous;
        for (const point of history) {
            line += `${previous !== undefined && point.at - previous <= 5 ? "L" : "M"}${x(point.at)},${y(point[key])} `;
            previous = point.at;
        }
        svg.append(
            make("path", { d: line, class: `history-line history-${key}` }),
        );
    }
    for (const point of history) {
        const hit = make("rect", {
            x: x(point.at) - 4,
            y: 0,
            width: 8,
            height: 134,
            fill: "transparent",
        });
        const hint = make("title", {});
        hint.textContent = `${end - point.at}s ago · ${quantiles.map((q) => `${title(q)} ${point[q].toFixed(2)} ms`).join(" · ")}`;
        hit.append(hint);
        svg.append(hit);
    }
    for (const fraction of [0, 0.5, 1]) {
        const ago = Math.round(span * (1 - fraction));
        const text = make("text", {
            x: 40 + fraction * 548,
            y: 151,
            "text-anchor":
                fraction === 0 ? "start" : fraction === 1 ? "end" : "middle",
        });
        text.textContent =
            ago === 0 ? "Now" : ago < 60 ? `${ago}s ago` : `${ago / 60}m ago`;
        svg.append(text);
    }
    label.textContent = `${range.selectedOptions[0].text} history · 5-second intervals · milliseconds`;
}
