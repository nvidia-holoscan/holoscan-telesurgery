// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { hasSelection } from "./ui.js";

const dialog = document.querySelector("#log-dialog"),
    output = document.querySelector("#log-output"),
    copy = document.querySelector("#copy-log"),
    status = document.querySelector("#log-status");
let controller, timer;
function stop() {
    clearTimeout(timer);
    controller?.abort();
}
export function openLog(title, url) {
    stop();
    const current = new AbortController();
    controller = current;
    document.querySelector("#log-title").textContent = title;
    output.textContent = "Loading…";
    copy.disabled = true;
    output.scrollTop = 0;
    status.textContent = "";
    if (!dialog.open) dialog.showModal();
    async function refresh() {
        try {
            const response = await fetch(url, { signal: current.signal });
            if (!response.ok)
                throw new Error(`Cannot load log: ${response.statusText}`);
            const log = await response.json();
            if (current.signal.aborted) return;
            const follow =
                output.scrollHeight - output.scrollTop - output.clientHeight <
                24;
            const selecting = hasSelection(output);
            const text = log.text || "Waiting for output…";
            if (!selecting && output.textContent !== text) {
                output.textContent = text;
                if (follow) output.scrollTop = output.scrollHeight;
            }
            copy.disabled = !log.text;
            status.textContent = selecting
                ? "Updates paused while text is selected"
                : `Latest 100 lines · ${log.updated_seconds_ago === null ? "No output yet" : `Last output ${log.updated_seconds_ago}s ago`}`;
        } catch (error) {
            if (!current.signal.aborted) status.textContent = error.message;
        } finally {
            if (!current.signal.aborted && dialog.open)
                timer = setTimeout(refresh, 1000);
        }
    }
    refresh();
}
document.querySelector("#close-log").onclick = () => dialog.close();
copy.onclick = async () => {
    try {
        await navigator.clipboard.writeText(output.textContent);
        status.textContent = "Logs copied";
    } catch {
        const selection = window.getSelection();
        selection.selectAllChildren(output);
        status.textContent = "Press Ctrl+C to copy the selected logs";
    }
};
dialog.addEventListener("close", stop);
