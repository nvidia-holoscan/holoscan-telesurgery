// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, action } from "./ui.js";

export function robotStartup(refresh) {
    const dialog = $("#robot-start-dialog"),
        form = $("#robot-start-form"),
        ready = $("#robot-operator-ready"),
        submit = $("#confirm-robot-start"),
        error = $("#robot-start-error");
    let selected,
        pending = false;
    ready.onchange = () => {
        submit.disabled = pending || !ready.checked;
    };
    $("#cancel-robot-start").onclick = () => dialog.close();
    form.onsubmit = async (event) => {
        event.preventDefault();
        if (pending || !ready.checked) return;
        pending = true;
        submit.disabled = ready.disabled = true;
        submit.textContent = "Starting…";
        error.hidden = true;
        try {
            await action("robot.start", { id: selected, confirmed: true });
            dialog.close();
            await refresh();
        } catch (failure) {
            error.textContent = failure.message;
            error.hidden = false;
        } finally {
            pending = false;
            ready.disabled = false;
            submit.disabled = !ready.checked;
            submit.textContent = "Bring online";
        }
    };
    return (robot) => {
        if (pending) return;
        selected = robot.id;
        ready.checked = false;
        submit.disabled = true;
        error.hidden = true;
        $("#robot-start-name").textContent = robot.name;
        dialog.showModal();
    };
}
