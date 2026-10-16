// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { action } from "./ui.js";

export function robotStartup(refresh) {
    const pending = new Set();
    return async robot => {
        if (pending.has(robot.id)) return;
        pending.add(robot.id);
        try {
            await action("robot.start", {id: robot.id});
            await refresh();
        } finally {
            pending.delete(robot.id);
        }
    };
}
