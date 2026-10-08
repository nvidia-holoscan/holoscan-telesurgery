// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, action, notice } from "./ui.js";

export function nodeSettings(refresh) {
    const removal = $("#remove-node-dialog"),
        confirm = $("#confirm-remove-node");
    let selected;
    $("#cancel-remove-node").onclick = () => removal.close();
    $("#remove-node-form").onsubmit = async (event) => {
        event.preventDefault();
        confirm.disabled = true;
        try {
            await action("node.remove", { id: selected });
            removal.close();
            await refresh();
        } catch (error) {
            notice(error);
        } finally {
            confirm.disabled = false;
        }
    };
    return {
        remove(node) {
            selected = node.id;
            $("#remove-node-name").textContent = node.name;
            removal.showModal();
        },
    };
}
