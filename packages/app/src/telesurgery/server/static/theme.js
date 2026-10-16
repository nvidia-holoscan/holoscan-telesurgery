// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const selector = document.getElementById("theme-choice");
let role;
const key = () => `telesurgery:theme:${role}`;

function saved(name) {
    try { return localStorage.getItem(name); } catch { return null; }
}

function apply(value) {
    const theme = ["light", "dark"].includes(value) ? value : role === "patient" ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    selector.value = theme;
    document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#141c24" : "#ffffff";
}

export function setThemeRole(next) {
    if (!["patient", "surgeon"].includes(next) || role === next) return;
    role = next;
    apply(saved(key()));
    try { localStorage.setItem("telesurgery:theme-role", role); } catch { /* Private browser storage. */ }
}

setThemeRole(saved("telesurgery:theme-role") || "surgeon");
selector.addEventListener("change", () => {
    apply(selector.value);
    try { localStorage.setItem(key(), selector.value); } catch { /* The choice still works this visit. */ }
});
window.addEventListener("storage", event => {
    if (event.key === key()) apply(event.newValue);
});
