// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

document.querySelector("#access-form").addEventListener("submit", async event => {
    event.preventDefault();
    const error = document.querySelector("#access-error");
    const button = event.currentTarget.querySelector("button");
    button.disabled = true;
    try {
        const response = await fetch("/api/login", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({token: document.querySelector("#access-code").value.trim()}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
        location.replace("/");
    } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
    } finally {
        button.disabled = false;
    }
});
