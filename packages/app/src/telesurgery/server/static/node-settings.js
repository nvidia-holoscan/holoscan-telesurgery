// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, action, notice } from "./ui.js";

export function nodeSettings(refresh) {
    const dialog = $("#node-dialog"),
        form = $("#node-form");
    const mode = form.elements.mode,
        submit = $("#connect-node"),
        error = $("#node-error");
    function update() {
        const running = mode.value === "service";
        $("#node-service-fields").hidden = !running;
        $("#node-service-fields").disabled = !running;
        $("#node-ssh-fields").hidden = running;
        $("#node-ssh-fields").disabled = running;
        $("#deploy-environment").hidden = running;
        form.elements.environment.disabled = running;
        submit.textContent = running ? "Connect node" : "Deploy node";
        error.hidden = true;
    }
    mode.onchange = update;
    function open(address) {
        if (address) {
            mode.value = "service";
            form.elements.address.value = address;
        }
        update();
        dialog.showModal();
    }
    $("#add-node").onclick = () => open();
    $("#cancel-node").onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
        form.elements.code.value = "";
    });
    form.onsubmit = async (event) => {
        event.preventDefault();
        const data = new FormData(form),
            running = data.get("mode") === "service";
        submit.disabled = true;
        mode.disabled = true;
        error.hidden = true;
        submit.textContent = running ? "Connecting…" : "Deploying…";
        try {
            await action(
                running ? "node.connect" : "node.add",
                running
                    ? {
                          address: data.get("address").trim(),
                          code: data.get("code").trim(),
                      }
                    : {
                          target: data.get("target").trim(),
                          sdk: Number(data.get("sdk")),
                          environment: data.get("environment") || null,
                      },
            );
            dialog.close();
            await refresh();
        } catch (failure) {
            error.textContent = failure.message;
            error.hidden = false;
        } finally {
            submit.disabled = false;
            mode.disabled = false;
            submit.textContent = running ? "Connect node" : "Deploy node";
        }
    };
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
    const environmentDialog = $("#environment-dialog"),
        environmentForm = $("#environment-form"),
        applyEnvironment = $("#apply-environment"),
        environmentError = $("#environment-error");
    let environmentNode;
    $("#cancel-environment").onclick = () => environmentDialog.close();
    environmentForm.onsubmit = async (event) => {
        event.preventDefault();
        applyEnvironment.disabled = true;
        environmentError.hidden = true;
        try {
            await action("node.environment", {
                id: environmentNode.id,
                environment: environmentForm.elements.environment.value || null,
            });
            environmentDialog.close();
            await refresh();
        } catch (failure) {
            environmentError.textContent = failure.message;
            environmentError.hidden = false;
        } finally {
            applyEnvironment.disabled = false;
        }
    };
    return {
        open,
        environment(node) {
            environmentNode = node;
            $("#environment-node").textContent = node.name;
            environmentForm.elements.environment.value = node.environment || "";
            environmentError.hidden = true;
            environmentDialog.showModal();
        },
        remove(node) {
            selected = node.id;
            $("#remove-node-name").textContent = node.name;
            removal.showModal();
        },
    };
}
