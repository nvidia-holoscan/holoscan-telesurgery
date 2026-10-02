// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { latencyReader } from "./latency.js";
import { latencyView } from "./metrics.js";
import { action, hasSelection } from "./ui.js";
import { setIcon } from "./icons.js";

export function metricsMonitor(container, peers) {
    container.innerHTML = `<div class="metrics-toolbar"><p id="metrics-updated" role="status">Waiting for metrics…</p><label>Refresh<select id="report-interval" aria-label="Metrics refresh interval"><option value="1000">1 second</option><option value="5000" selected>5 seconds</option><option value="10000">10 seconds</option><option value="30000">30 seconds</option></select></label><button id="reset-metrics" class="secondary small">Reset metrics</button></div><div id="report-output"></div>`;
    const output = container.querySelector("#report-output"),
        status = container.querySelector("#metrics-updated"),
        interval = container.querySelector("#report-interval"),
        reset = container.querySelector("#reset-metrics");
    setIcon(reset, "reset");
    let owner = container.ownerDocument,
        running = false,
        controller,
        timer,
        read,
        render,
        device,
        pendingReset = false;
    function cancel() {
        clearTimeout(timer);
        controller?.abort();
    }
    function reader() {
        read?.close();
        read = latencyReader(peers, device);
    }
    async function refresh() {
        if (!running || owner.hidden || pendingReset) return;
        cancel();
        const current = new AbortController();
        controller = current;
        try {
            const report = await read(current.signal);
            if (!running || current.signal.aborted) return;
            const selecting = hasSelection(output);
            if (!selecting) render(output, report);
            status.textContent = selecting
                ? "Updates paused while text is selected"
                : report.status;
            status.dataset.state = "live";
        } catch (error) {
            if (!current.signal.aborted) {
                status.textContent = error.message;
                status.dataset.state = "error";
            }
        } finally {
            if (running && !current.signal.aborted)
                timer = setTimeout(refresh, Number(interval.value));
        }
    }
    interval.onchange = refresh;
    reset.onclick = async () => {
        cancel();
        const resetting = read;
        pendingReset = true;
        reset.disabled = true;
        try {
            await action("metrics.reset", { device });
            resetting?.close(true);
            if (read === resetting) reader();
        } catch (error) {
            status.textContent = error.message;
            status.dataset.state = "error";
        } finally {
            pendingReset = false;
            reset.disabled = false;
            if (running) refresh();
        }
    };
    function visibility() {
        if (owner.hidden) {
            cancel();
            read?.close();
        } else if (running) refresh();
    }
    owner.addEventListener("visibilitychange", visibility);
    return {
        relocate() {
            const wasHidden = owner.hidden;
            owner.removeEventListener("visibilitychange", visibility);
            owner = container.ownerDocument;
            owner.addEventListener("visibilitychange", visibility);
            if (owner.hidden || wasHidden) visibility();
        },
        start(options) {
            cancel();
            running = true;
            device = options.device;
            reader();
            render = latencyView(options.device);
            output.replaceChildren();
            refresh();
        },
        stop() {
            running = false;
            cancel();
            read?.close();
        },
    };
}
