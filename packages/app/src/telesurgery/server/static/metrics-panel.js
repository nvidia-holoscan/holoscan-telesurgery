// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { metricsMonitor } from "./monitor.js";
import { notice } from "./ui.js";
import { setIcon } from "./icons.js";

// Move the existing view so browser timing keeps using the dashboard's video peers.
export function metricsPanel(panel, peers) {
    const home = panel.parentNode,
        backdrop = document.querySelector("#metrics-backdrop"),
        anchor = panel.nextSibling,
        title = panel.querySelector("#metrics-title"),
        popout = panel.querySelector("#popout-metrics"),
        dismiss = panel.querySelector("#close-metrics"),
        monitor = metricsMonitor(
            panel.querySelector("#stream-metrics"),
            peers,
        );
    let popup, origin;

    function shade(visible) {
        backdrop.hidden = !visible;
        panel.setAttribute("aria-modal", String(visible));
        for (const content of document.querySelectorAll(
            ".app-header, .app-shell",
        ))
            content.inert = visible;
    }

    function dock() {
        const previous = popup;
        popup = null;
        home.insertBefore(panel, anchor);
        shade(!panel.hidden);
        setIcon(popout, "popout", "Pop out");
        monitor.relocate();
        previous?.close();
        if (!panel.hidden) popout.focus();
    }

    function close() {
        if (panel.hidden) return;
        panel.hidden = true;
        shade(false);
        monitor.stop();
        if (popup) dock();
        origin?.focus();
    }

    function escape(event) {
        if (
            event.key === "Escape" &&
            event.currentTarget.document === panel.ownerDocument
        )
            close();
    }

    popout.onclick = () => {
        if (popup) return dock();
        const opened = window.open(
            "",
            "_blank",
            "popup,width=1180,height=900",
        );
        if (!opened) {
            notice(
                "Allow pop-ups for this dashboard to open metrics in a separate window.",
            );
            return;
        }
        popup = opened;
        shade(false);
        const doc = opened.document;
        doc.title = `${title.textContent} · Metrics`;
        doc.documentElement.lang = document.documentElement.lang;
        const viewport = doc.createElement("meta");
        viewport.name = "viewport";
        viewport.content = "width=device-width, initial-scale=1";
        doc.head.append(viewport);
        for (const source of document.querySelectorAll(
            'link[rel="stylesheet"]',
        )) {
            const link = doc.createElement("link");
            link.rel = "stylesheet";
            link.href = source.href;
            doc.head.append(link);
        }
        doc.body.className = "metrics-popout";
        doc.body.append(panel);
        setIcon(popout, "dock", "Dock");
        opened.addEventListener("keydown", escape);
        opened.addEventListener(
            "pagehide",
            () => {
                if (popup === opened) close();
            },
            { once: true },
        );
        monitor.relocate();
        dismiss.focus();
    };
    dismiss.onclick = close;
    backdrop.onclick = close;
    window.addEventListener("keydown", escape);
    window.addEventListener("pagehide", close);

    return {
        open(options) {
            origin = document.activeElement;
            title.textContent = options.title;
            panel.hidden = false;
            shade(!popup);
            monitor.start(options);
            if (popup) {
                popup.document.title = `${options.title} · Metrics`;
                popup.focus();
            }
            dismiss.focus();
        },
        close,
    };
}
