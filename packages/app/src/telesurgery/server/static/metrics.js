// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { pathView, stages } from "./path-view.js";
import { element } from "./ui.js";

// Presentation only: no timers, network requests, or video work.
const number = (value) => (Number.isFinite(value) ? value.toFixed(2) : "—");
const count = (value) =>
    Number.isFinite(value) ? value.toLocaleString() : "—";
function card(label, key, unit) {
    return `<article class="metric-card" data-card="${key}">
        <h3>${label}</h3><div class="metric-value"><strong>—</strong><span>${unit}</span></div>
        <p class="metric-caption"></p>
        <svg class="metric-trend" viewBox="0 0 300 48" preserveAspectRatio="none" role="img" aria-label="${label} trend">
            <title></title><path class="trend-line"></path>
        </svg><p class="trend-caption"></p>
    </article>`;
}

function table(label) {
    return `<div class="metrics-table-scroll" tabindex="0" role="region" aria-label="${label}">
        <table class="metrics-table"><caption class="sr-only">${label}, in milliseconds</caption>
        <thead><tr><th scope="col">Stage</th><th scope="col">P50</th><th scope="col">P95</th><th scope="col">P99</th><th scope="col">P99.9</th></tr></thead><tbody></tbody></table>
    </div>`;
}

function rows(target, values, bars = false) {
    const max = Math.max(
        0.001,
        ...values.map(([, sample]) => sample?.p99 || 0),
    );
    target.replaceChildren(
        ...values.map(
            ([label, sample, unavailable = "Collecting samples…"]) => {
                const row = document.createElement("tr");
                const heading = element("th", label);
                heading.scope = "row";
                if (sample?.count) {
                    heading.append(
                        element(
                            "small",
                            `${count(sample.window_count)} samples`,
                        ),
                    );
                    if (bars) {
                        const bar = element("span", "", "stage-bar");
                        bar.style.width = `${Math.max(0, (sample.p99 / max) * 100)}%`;
                        bar.setAttribute("aria-hidden", "true");
                        heading.append(bar);
                    }
                    row.append(
                        heading,
                        ...["p50", "p95", "p99", "p99_9"].map((key) =>
                            element("td", number(sample[key])),
                        ),
                    );
                } else {
                    const empty = element(
                        "td",
                        unavailable,
                        "metric-unavailable",
                    );
                    empty.colSpan = 4;
                    row.append(heading, empty);
                }
                return row;
            },
        ),
    );
}

function counters(target, values) {
    target.replaceChildren(
        ...values.flatMap(([label, value, alert = false]) => [
            element("dt", label),
            element(
                "dd",
                typeof value === "number" ? count(value) : value,
                alert ? "metric-alert" : "",
            ),
        ]),
    );
}

function trend(target, history, key) {
    const values = history.map((item) => item[key]).filter(Number.isFinite);
    const low = Math.min(...values),
        high = Math.max(...values);
    const start = history[0]?.at,
        end = history.at(-1)?.at;
    let path = "",
        connected = false;
    if (values.length > 1 && end > start) {
        const padding = Math.max((high - low) * 0.2, high * 0.03, 0.01);
        for (const item of history) {
            if (!Number.isFinite(item[key])) {
                connected = false;
                continue;
            }
            const x = 2 + (296 * (item.at - start)) / (end - start);
            const y =
                44 -
                (40 * (item[key] - low + padding)) / (high - low + padding * 2);
            path += `${connected ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)} `;
            connected = true;
        }
    }
    target.querySelector("path").setAttribute("d", path);
    target.querySelector("title").textContent = values.length
        ? `Range ${number(low)} to ${number(high)}`
        : "Waiting for measurements";
    target.parentElement.querySelector(".trend-caption").textContent = path
        ? `${number(low)}–${number(high)} · last ${Math.round((end - start) / 1000)} s`
        : "Trend appears after two measured updates";
}

export function latencyView(selected) {
    let root, latest;
    return (output, report) => {
        latest = report;
        if (root !== output.firstElementChild) {
            output.innerHTML = `<div class="metrics-dashboard">

                <div class="metrics-overview">
                    ${card("Decoded frame rate", "fps", "fps")}
                    ${card("Total latency · P99", "delivery", "ms")}
                    ${card("Encode · P99", "encode", "ms")}
                    ${card("Decode · P99", "decode", "ms")}
                </div>
                <p class="metrics-empty" hidden></p>
                <section class="metrics-panel" id="metrics-robot" hidden><div class="metrics-panel-heading"><h3 id="robot-metric-name"></h3><span>Milliseconds</span></div><p id="robot-metric-status"></p>${table("Robot command percentiles")}<p class="metrics-footnote">Successful commands only, timed in this service. Browser input and physical motion completion are not measured.</p></section>
                <div class="metrics-columns">
                    <div class="metrics-main">
                        <section class="metrics-panel" id="metrics-pipeline">
                            <div class="metrics-panel-heading"><h3>Latency (ms)</h3><span id="metrics-path-count"></span></div>
                            <p class="metrics-description" id="metrics-path-note"></p>
                            <div class="latency-bars" aria-label="Latency breakdown by percentile"></div>
                            <div class="latency-legend" hidden><span><i class="stage-patient"></i>Source</span><span><i class="stage-encode"></i>Encode</span><span><i class="stage-transport"></i>Transport</span><span><i class="stage-surgeon"></i>Surgeon</span><span><i class="stage-decode"></i>Decode</span><span><i class="stage-display"></i>Display</span></div>
                            <div class="latency-history"><div class="metrics-panel-heading"><h4>Latency over time</h4><select class="history-range" aria-label="Latency history window"><option value="60">1 min</option><option value="300" selected>5 min</option><option value="1800">30 min</option><option value="3600">1 hr</option></select></div><div class="history-legend"><span class="history-p50">P50</span><span class="history-p95">P95</span><span class="history-p99">P99</span><span class="history-p99_9">P99.9</span></div><svg viewBox="0 0 600 158" role="img" aria-label="Latency percentiles over time"></svg><p class="metrics-footnote"></p></div>
                            ${table("Latency breakdown")}
                            <div class="browser-stages" hidden>
                                <div><span>Jitter buffering · avg</span><strong id="metrics-buffer">—</strong></div>
                                <div><span>Browser decoding · avg</span><strong id="metrics-decode">—</strong></div>
                            </div>
                            <p class="metrics-footnote" id="metrics-sampling"></p>
                        </section>
                        <section class="metrics-panel" id="metrics-connection">
                            <div class="metrics-panel-heading"><h3>Connection and control</h3><span>Milliseconds</span></div>
                            ${table("Connection percentiles")}
                            <p class="metrics-footnote">Includes service processing. Robot timing ends at acknowledgement, not motion completion.</p>
                        </section>
                    </div>
                    <aside class="metrics-side">
                        <section class="metrics-panel" id="metrics-health">
                            <div class="metrics-panel-heading"><h3>Stream health</h3><span class="metric-badge" id="metrics-flow"></span></div>
                            <dl id="metrics-stream-counters"></dl>
                            <div id="metrics-browser-health"><h4>Browser counters</h4><p>Since metrics opened or reset</p><dl id="metrics-browser-counters"></dl></div>
                            <div class="metrics-cadence"><h4>Frame spacing</h4><dl class="metrics-quantiles" id="metrics-cadence"></dl><span>Milliseconds · cadence, not transit delay</span></div>
                        </section>
                        <section class="metrics-panel metrics-clock">
                            <div class="metrics-panel-heading"><h3>Clock accuracy</h3></div>
                            <span class="metric-badge" id="metrics-clock-state"></span>
                            <p id="metrics-clock-detail"></p><p class="metrics-footnote" id="metrics-clock-source"></p>
                        </section>
                    </aside>
                </div>
                <details class="metrics-notes"><summary>How to read these measurements</summary>
                    <p>Each stacked bar is a total-latency percentile. Its stages come from the same ranked frames and add to that total; they are not separate stage percentiles. Stage cards show each stage’s own P99.</p>
                    <p>Source timing stops at the camera node’s transport handoff. Browser timing ends at estimated display time. Holoviz timing stops at frame handoff; native rendering and scanout are not measured. Sensor exposure is not measured.</p>
                    <p>Timing starts when a frame buffer reaches the application. Frame preparation includes our conversions, copies and local handoff; simulator rendering and device acquisition before buffer delivery are excluded. Encode includes input conversion and GPU encoding; Decode includes output preparation. WebRTC + display includes local transmission, buffering and display scheduling, excluding Decode.</p>
                    <p>View processing measures native depth composition and crop selection after decode, separately from Holoviz handoff. Zoom sampling happens during rendering: browser compositor work is included in WebRTC + display and has no separate GPU timer; native rendering remains unmeasured. Camera-side zoom happens before buffer delivery and is not timed separately.</p>
                    <p>Uncompressed streams use Pack (buffer copies for sending) and Upload (GPU upload and display color conversion), with no encoding or decoding.</p>
                    <p>Frame size includes encoded or raw video, the application message header and framing bytes on the node-to-viewer transport. TLS records and TCP/IP overhead are excluded. Video payload excludes application framing.</p>
                    <p>Samples are bounded to 10,000 and skip the first 2 seconds. Browser frame matching runs only while metrics is open. Missing timestamps leave the total unavailable; cross-host estimates include clock uncertainty. Reset clears samples without interrupting video.</p>
                </details>
            </div>`;
            root = output.firstElementChild;
        }
        update();
        if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
            output.ownerDocument
                .querySelector("#metrics-updated")
                ?.animate([{ opacity: 0.4 }, { opacity: 1 }], {
                    duration: 350,
                });
        }

        function update() {
            const $ = (selector) => root.querySelector(selector);
            const { state, streams } = latest;
            const patient = state.role === "patient";
            const robots = state.metric_robots || [];
            const robot = robots.find((r) => r.id === selected);
            $("#metrics-robot").hidden = !robot;
            $(".metrics-columns").hidden = Boolean(robot);
            $(".metrics-overview").hidden = Boolean(robot);
            if (robot) {
                $(".metrics-empty").hidden = true;
                $("#robot-metric-name").textContent = robot.name;
                $("#robot-metric-status").textContent =
                    `${robot.status} · ${robot.owner ? `Controlled by ${robot.owner}` : "No control owner"}${robot.error ? ` · ${robot.error}` : ""}`;
                rows($("#metrics-robot tbody"), [
                    [
                        patient
                            ? "Patient validation → controller acknowledgement"
                            : "Surgeon command round trip",
                        state.robot_timings?.[robot.id],
                        "No successful commands sampled yet",
                    ],
                ]);
                return;
            }
            const stream = streams.find(({ id }) => id === selected);
            const {
                report: stats = {},
                path = {},
                browser,
                holoviz,
                resolved,
                history = [],
                raw = false,
            } = stream || {};
            const metrics = stats.steady_metrics || {};
            const collecting = !stats.frames;
            const delivery = collecting
                ? "Waiting for timing samples"
                : stats.delivery_status || "Clock synchronization required";
            const timing = state.timings || {};
            const decoded = patient || holoviz ? stream?.fps : browser?.fps;
            const setCard = (key, value, caption, samples) => {
                const card = $(`[data-card="${key}"]`);
                card.querySelector("strong").textContent = number(value);
                card.querySelector(".metric-caption").textContent = caption;
                card.classList.toggle(
                    "is-unavailable",
                    !Number.isFinite(value),
                );
                trend(card.querySelector("svg"), samples, key);
            };
            $('[data-card="fps"] h3').textContent = patient
                ? "Source frame rate"
                : raw
                  ? "Viewer frame rate"
                  : "Decoded frame rate";
            $('[data-card="encode"] h3').textContent = raw
                ? "Pack · P99"
                : "Encode · P99";
            $('[data-card="decode"] h3').textContent = raw
                ? "Upload · P99"
                : "Decode · P99";
            $('[data-card="delivery"] h3').textContent = patient
                ? "Source latency · P99"
                : "Total latency · P99";
            $('[data-card="decode"]').hidden = patient;
            $(".metrics-overview").classList.toggle("patient-metrics", patient);
            setCard(
                "fps",
                decoded,
                patient
                    ? "Camera node · interval average"
                    : holoviz
                      ? "Holoviz · interval average"
                      : browser?.detail || "Waiting for decoded frames",
                history,
            );
            setCard(
                "delivery",
                path.total?.p99,
                (!Number.isFinite(path.total?.p99) && path.unavailable_reason) || (patient
                    ? "Buffer → source transport handoff"
                    : holoviz
                      ? "Buffer → Holoviz handoff"
                      : "Buffer → display estimate") +
                    (path.error_ms > 0
                        ? ` · ±${number(path.error_ms)} ms`
                        : ""),
                history,
            );
            setCard(
                "encode",
                metrics[raw ? "pack_ms" : "encode_ms"]?.p99,
                raw
                    ? "Source · copies to transport buffer"
                    : "Source · includes input conversion",
                history,
            );
            setCard(
                "decode",
                holoviz
                    ? metrics[raw ? "unpack_ms" : "decode_ms"]?.p99
                    : path.decode?.p99,
                raw
                    ? "Surgeon · GPU upload and color conversion"
                    : holoviz
                      ? "Surgeon · GPU output"
                      : "Surgeon · browser output",
                history,
            );
            $(".metrics-empty").hidden = Boolean(stream);
            $(".metrics-empty").textContent = patient
                ? "Discovered devices will appear here."
                : state.session?.status === "approved"
                  ? "Show a camera to see live stream metrics."
                  : "Patient approval is required to receive camera streams.";
            $("#metrics-pipeline").hidden = !stream;
            $("#metrics-health").hidden = !stream;
            $("#metrics-connection").hidden = patient;
            rows($("#metrics-connection tbody"), [
                [
                    "Patient status round trip",
                    timing.patient_round_trip_ms,
                    state.timings
                        ? "Collecting samples…"
                        : "Restart the surgeon service to enable timing",
                ],
                ...(state.session?.robot
                    ? [
                          [
                              "Robot command acknowledgement",
                              timing.control_ack_ms,
                              "No commands yet",
                          ],
                      ]
                    : []),
            ]);
            rows(
                $("#metrics-pipeline tbody"),
                [
                    ["Frame preparation", metrics.acquisition_ms],
                    ["Processing queue", metrics.encoder_queue_ms],
                    [
                        raw ? "Pack" : "Encode",
                        metrics[raw ? "pack_ms" : "encode_ms"],
                    ],
                    ...(!patient
                        ? [
                              [
                                  "Stream transport",
                                  resolved ? metrics.delivery_ms : null,
                                  delivery,
                              ],
                              ["Receive queue", metrics.receiver_queue_ms],
                          ]
                        : []),
                    ...(holoviz
                        ? [
                              [
                                  raw ? "Upload" : "Decode",
                                  metrics[raw ? "unpack_ms" : "decode_ms"],
                              ],
                              ["View processing", metrics.view_processing_ms],
                              ["Holoviz handoff", metrics.render_submit_ms],
                          ]
                        : []),
                ],
                true,
            );
            const complete = pathView($("#metrics-pipeline"), path);
            $(".latency-legend").hidden = !complete;
            $("#metrics-path-count").textContent = path.sampled
                ? `${count(path.count)} / ${count(path.sampled)} frames`
                : "";
            $("#metrics-path-note").textContent = complete
                ? "Stages add to each total. Columns follow the same frames."
                : path.unavailable_reason
                  ? `${path.unavailable_reason} Separate stage timings below.`
                : path.missing?.length
                  ? `Total unavailable: ${path.missing.map((k) => stages[k]?.[0] || k).join(", ")}. Separate stage timings below.`
                  : patient
                    ? "Waiting for traced frames sent to a viewer. Separate stage timings below."
                    : "Matching displayed frames… Separate stage timings below.";
            $(".browser-stages").hidden =
                patient || holoviz || !stream || complete;
            $("#metrics-buffer").textContent = `${number(browser?.buffer)} ms`;
            $("#metrics-decode").textContent = `${number(browser?.decode)} ms`;
            $("#metrics-sampling").textContent = patient
                ? "Camera buffer → source transport handoff. One sample per sent frame and viewer."
                : holoviz
                  ? `Buffer → Holoviz handoff.${Number.isFinite(path.error_ms) ? ` Timing uncertainty ±${number(path.error_ms)} ms.` : ""} Native rendering and scanout are not measured.`
                  : `Buffer → estimated browser display.${Number.isFinite(path.error_ms) ? ` Clock error ±${number(path.error_ms)} ms.` : ""} Sensor exposure and screen scanout are not measured.`;
            const flow = Number.isFinite(decoded) ? decoded : stream?.fps;
            $("#metrics-flow").textContent =
                flow > 0
                    ? "Receiving"
                    : flow === 0
                      ? "No new frames"
                      : "Collecting";
            $("#metrics-flow").dataset.tone =
                flow > 0 ? "good" : flow === 0 ? "warn" : "neutral";
            counters($("#metrics-stream-counters"), [
                [
                    holoviz
                        ? raw
                            ? "Uploaded at viewer"
                            : "Decoded at viewer"
                        : "Received at service",
                    `${number(stream?.fps)} fps`,
                ],
                ...(!holoviz
                    ? [
                          [
                              "Last frame age",
                              `${number(stats.last_frame_age_ms)} ms`,
                          ],
                      ]
                    : []),
                [
                    "Transport frame · P99",
                    `${number(metrics.transport_frame_bytes?.p99 / 1024)} KiB`,
                ],
                [
                    "Video payload · P99",
                    `${number(metrics.payload_bytes?.p99 / 1024)} KiB`,
                ],
                [
                    "Sequence gaps",
                    stats.sequence_gaps ?? "—",
                    stats.sequence_gaps > 0,
                ],
                ["Sequence resets", stats.sequence_resets ?? "—"],
            ]);
            $("#metrics-browser-health").hidden = patient || holoviz || !stream;
            counters($("#metrics-browser-counters"), [
                [
                    "Dropped frames",
                    browser?.dropped ?? "—",
                    browser?.dropped > 0,
                ],
                ["Lost packets", browser?.lost ?? "—", browser?.lost > 0],
                ["Freezes", browser?.freezes ?? "—", browser?.freezes > 0],
                ["Local service RTT", `${number(browser?.rtt)} ms`],
            ]);
            $("#metrics-cadence").replaceChildren(
                ...["p50", "p95", "p99", "p99_9"].map((key) => {
                    const item = document.createElement("div");
                    item.append(
                        element("dt", key.replace("_", ".").toUpperCase()),
                        element(
                            "dd",
                            number(metrics.receive_interval_ms?.[key]),
                        ),
                    );
                    return item;
                }),
            );
            const clock = state.clock;
            const shared = delivery === "Same host · monotonic clock";
            const relative = delivery === "Relative clock estimate";
            const uncertainty = Number.isFinite(path.error_ms)
                ? path.error_ms
                : stats.delivery_clock_error_ms;
            const badge = $("#metrics-clock-state");
            badge.textContent = patient
                ? "Source monotonic clock"
                : collecting
                  ? "Collecting samples"
                  : shared
                    ? "Shared monotonic clock"
                    : resolved
                      ? relative
                          ? "Relative clock estimate"
                          : "Synchronized UTC"
                      : "Delivery timing unavailable";
            badge.dataset.tone =
                !patient && collecting
                    ? "neutral"
                    : patient || resolved
                      ? "good"
                      : "warn";
            $("#metrics-clock-detail").textContent = patient
                ? "Timing stays on the camera node, from buffer delivery to transport handoff."
                : collecting
                  ? "Clock quality is checked when frames arrive."
                  : shared
                    ? "Source and viewer share a monotonic clock."
                    : Number.isFinite(uncertainty)
                      ? `Timing uncertainty ±${number(uncertainty)} ms.${relative ? " Measured between connected services; system clocks are unchanged." : ""}`
                      : "Clock quality is not verified for this stream. Local stage timings remain available.";
            $("#metrics-clock-source").textContent =
                !patient &&
                !relative &&
                !shared &&
                clock?.state === "synchronized"
                    ? `Surgeon UTC error ±${number(clock.error_ms)} ms · ${clock.source}`
                    : "";
        }
    };
}
