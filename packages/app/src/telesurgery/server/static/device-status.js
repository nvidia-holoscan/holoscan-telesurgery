// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export function deviceStatus(item, robot = false) {
    if (item.node_online === false || (!robot && item.status === "offline"))
        return ["Node offline", "warning"];
    if (item.status === "disconnected") return ["Disconnected", "neutral"];
    if (item.error || item.controller?.status === "error")
        return [robot ? "Control error" : "Error", "error"];
    if (item.stale || item.status === "stale")
        return ["Feedback stale", "warning"];
    if (item.status === "starting")
        return [robot ? "Connecting" : "Starting", "warning"];
    if (item.status === "online" || item.status === "live")
        return [robot ? "Connected" : "Live", "online"];
    if (item.controller?.status === "running")
        return ["Waiting for robot", "warning"];
    if (item.status === "unsupported")
        return [robot ? "Control not supported" : "Unavailable", "error"];
    if (item.status === "error") return ["Unavailable", "error"];
    return [robot ? "Offline" : "Stopped", "neutral"];
}
