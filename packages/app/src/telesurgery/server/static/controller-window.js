// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, notice } from "./ui.js";
import { motionValues } from "./robot-input.js";

// Each window runs its own input loop. Only the window completing the handover
// gets controls; background dashboard timers never drive the detached panel.
export function controllerWindow({ release, changed, selection, select }) {
    const compact = new URL(location.href).searchParams.has("controller");
    const parent = compact ? window.opener : null;
    let popup = null,
        active = !compact,
        transferring = false,
        handover = Promise.resolve(),
        saved;
    function snapshot() {
        return { robot: selection(), values: [...motionValues] };
    }
    function restore(value) {
        if (!value) return;
        for (const [key, number] of value.values) motionValues.set(key, number);
        select(value.robot);
    }
    async function stop() {
        active = false;
        changed();
        await release();
        return snapshot();
    }
    async function dock(child = popup, value) {
        if (!child || child !== popup || transferring) return;
        transferring = true;
        try {
            if (!value && !child.closed && child.telesurgeryController)
                value = await child.telesurgeryController.stop();
            else if ((value || saved)?.robot)
                // A window closed with its title-bar X cannot await its own
                // release. Finish that request here before restoring input.
                await release((value || saved).robot);
            restore(value || saved);
        } catch (error) {
            notice(error);
        } finally {
            child.close();
            popup = null;
            active = true;
            transferring = false;
            changed();
        }
    }
    const control = {
        compact,
        get enabled() {
            return active && !popup && !transferring;
        },
        get detached() {
            return !!popup;
        },
        async attach(child) {
            if (child !== popup)
                throw new Error("Open controls from the dashboard.");
            await handover;
            return saved;
        },
        stop,
        dock,
        focus() {
            popup?.focus();
        },
        async toggle() {
            if (compact) {
                await parent?.telesurgeryController?.dock(window);
                return;
            }
            if (popup) return dock();
            return control.open();
        },
        async open() {
            if (popup && !popup.closed) {
                popup.focus();
                return true;
            }
            const opened = window.open(
                "about:blank",
                "_blank",
                "popup,width=410,height=760",
            );
            if (!opened) {
                notice(
                    "Allow pop-ups for this dashboard to open robot controls.",
                );
                return false;
            }
            popup = opened;
            saved = snapshot();
            handover = stop();
            await handover;
            if (opened.closed) return dock(opened);
            const url = new URL(location.href);
            url.searchParams.set("controller", "1");
            url.hash = "";
            opened.location.replace(url.href);
            return true;
        },
    };
    // Same-origin access lets the opener await the child's release before
    // docking. A directly opened URL has no handover and never enables input.
    window.telesurgeryController = control;
    if (compact) {
        document.body.classList.add("controller-window");
        const fit = new ResizeObserver(() => {
            if (!active) return;
            const panel = $("#robots-panel");
            if (panel.hidden) return;
            const padding =
                parseFloat(getComputedStyle($("#content")).paddingTop) || 12;
            const height = Math.min(
                screen.availHeight,
                Math.ceil(
                    panel.getBoundingClientRect().height +
                        padding * 2 +
                        outerHeight -
                        innerHeight,
                ),
            );
            if (Math.abs(outerHeight - height) > 2)
                window.resizeTo(outerWidth, height);
        });
        fit.observe($("#robots-panel"));
        Promise.resolve().then(async () => {
            try {
                if (!parent || parent.closed)
                    throw new Error("Open controls from the dashboard.");
                restore(await parent.telesurgeryController.attach(window));
                active = true;
                changed();
            } catch (error) {
                notice(error);
            }
        });
    }
    window.addEventListener("pagehide", () => {
        active = false;
        if (compact && parent && !parent.closed)
            parent.telesurgeryController?.dock(window, snapshot());
        else popup?.close();
    });
    setInterval(() => {
        if (popup?.closed) dock(popup);
        if (compact && parent?.closed) {
            stop();
            window.close();
        }
    }, 500);
    return control;
}
