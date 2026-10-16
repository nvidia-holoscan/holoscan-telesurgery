// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { icon } from "./icons.js";

const trigger = document.getElementById("appearance-button");
const panel = document.getElementById("appearance-panel");
const choices = document.getElementById("theme-choices");
const themes = new Map([
    ["light", "Light"], ["dark", "Dark"], ["midnight", "Midnight"],
    ["ocean", "Ocean"], ["warm", "Warm"],
]);
for (const [value, name] of themes) {
    const label = document.createElement("label");
    label.className = "theme-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "color-theme";
    input.value = value;
    const preview = document.createElement("span");
    preview.className = "theme-preview";
    preview.dataset.theme = value;
    preview.setAttribute("aria-hidden", "true");
    preview.innerHTML = '<span class="theme-preview-bar"></span><span class="theme-preview-card"></span>';
    const text = document.createElement("span");
    text.textContent = name;
    label.append(input, preview, text, icon("check"));
    choices.append(label);
}
let role;
const key = () => `telesurgery:theme:${role}`;

function saved(name) {
    try { return localStorage.getItem(name); } catch { return null; }
}

function apply(value) {
    const theme = themes.has(value) ? value : role === "patient" ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    for (const input of choices.querySelectorAll("input")) input.checked = input.value === theme;
    trigger.title = `Appearance · ${themes.get(theme)}`;
    document.querySelector('meta[name="theme-color"]').content =
        getComputedStyle(document.documentElement).getPropertyValue("--theme-surface").trim() || "#ffffff";
}

export function setThemeRole(next) {
    if (!["patient", "surgeon"].includes(next) || role === next) return;
    role = next;
    document.getElementById("appearance-scope").textContent = `${role === "patient" ? "Patient" : "Surgeon"} dashboard`;
    apply(saved(key()));
    try { localStorage.setItem("telesurgery:theme-role", role); } catch { /* Private browser storage. */ }
}

setThemeRole(saved("telesurgery:theme-role") || "surgeon");
choices.addEventListener("change", event => {
    apply(event.target.value);
    try { localStorage.setItem(key(), event.target.value); } catch { /* The choice still works this visit. */ }
});
function positionPanel() {
    const bounds = trigger.getBoundingClientRect();
    panel.style.left = `${Math.max(12, Math.min(bounds.right - panel.offsetWidth, innerWidth - panel.offsetWidth - 12))}px`;
    panel.style.top = `${Math.max(12, Math.min(bounds.bottom + 10, innerHeight - panel.offsetHeight - 12))}px`;
}
panel.addEventListener("toggle", event => {
    const open = event.newState === "open";
    trigger.setAttribute("aria-expanded", String(open));
    if (open) {
        positionPanel();
        choices.querySelector("input:checked")?.focus({preventScroll: true});
    }
});
window.addEventListener("resize", () => { if (panel.matches(":popover-open")) positionPanel(); });
window.addEventListener("storage", event => {
    if (event.key === key()) apply(event.newValue);
});
