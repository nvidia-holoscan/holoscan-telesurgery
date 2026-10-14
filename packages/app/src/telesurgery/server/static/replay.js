// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { action, button, element, notice } from "./ui.js";
import { inputBlocked } from "./robot-input.js";

export function replayControls(robot, prepare, send, hold, refresh, feedback) {
    const control = button("Replay inputs", start, "secondary icon-button", "replay");
    const status = element("span", "", "replay-status");
    status.setAttribute("role", "status");
    status.hidden = true;
    control.hidden = true;
    let recording, active = false, allowed = false, busy = false, disposed = false;
    let generation = 0, lastTick = performance.now();
    let heartbeatBusy = false, lastHeartbeat = 0;
    const blocked = () => inputBlocked({allowUnfocused: active && robot.simulation});

    function blockedReason() {
        if (document.hidden) return "dashboard hidden";
        if (!document.hasFocus()) return "dashboard lost focus";
        return "input controls changed";
    }

    async function stop(completed = false, reason = "operator stopped replay") {
        if (!active) return;
        active = false;
        generation++;
        status.textContent = completed ? "Replay complete" : `Replay stopped · ${reason}`;
        if (!completed) {
            try { await action("replay.cancel", {id: robot.id}); }
            catch { /* Ownership loss and a disconnected patient also stop replay. */ }
        }
        await hold();
        await refresh();
    }

    async function start() {
        if (active || !allowed || !recording) return;
        control.blur();
        await prepare();
        if (!allowed || disposed || blocked()) return;
        active = true;
        const issued = ++generation;
        lastTick = performance.now();
        status.textContent = "Preparing replay…";
        status.hidden = false;
        busy = true;
        await refresh();
        try {
            await action("replay.start", {id: robot.id, recording: recording.id});
            if (issued !== generation) await action("replay.cancel", {id: robot.id});
        } catch (error) {
            notice(error);
            await stop(false, error.message);
        } finally { busy = false; }
    }

    async function poll() {
        const now = performance.now(), late = now - lastTick > 200;
        lastTick = now;
        if (!active || disposed) return;
        if (!allowed || blocked() || late) {
            await stop(false, !allowed ? "control no longer available"
                : blocked() ? blockedReason() : "dashboard timer delayed");
            return;
        }
        if (!heartbeatBusy && now - lastHeartbeat >= 100) {
            heartbeatBusy = true;
            lastHeartbeat = now;
            const issued = generation;
            action("replay.heartbeat", {id: robot.id})
                .catch(error => { if (issued === generation) { notice(error); stop(false, error.message); } })
                .finally(() => { heartbeatBusy = false; });
        }
        if (busy) return;
        busy = true;
        const issued = generation, started = now;
        try {
            const result = await action("replay.read", {id: robot.id});
            if (issued !== generation || !active) return;
            if ((!result.feedback_paced && performance.now() - started > 200) || blocked()) {
                await stop(false, blocked() ? blockedReason() : "timed replay response delayed");
                return;
            }
            if (result.state) feedback(result.state);
            status.textContent = result.waiting ? "Waiting for the other surgeon…"
                : result.waiting_peer ? "Waiting at handoff checkpoint…"
                : result.waiting_feedback ? `Replaying · ${Math.floor(result.elapsed)} s · waiting for feedback`
                : `Replaying · ${Math.floor(result.elapsed)} s`;
            if (result.request) {
                const [mode, command] = result.request;
                if (mode === "release") await hold();
                else if (!await send(mode === "grip" ? {velocity: command} : command, mode, result.speed_deg_s, result.run))
                    throw new Error("Replay motion was interrupted");
            }
            if (result.done) await stop(true);
        } catch (error) {
            if (issued === generation) { notice(error); await stop(false, error.message); }
        } finally { busy = false; }
    }

    const timer = setInterval(poll, 10);
    return {
        button: control, status,
        get active() { return active; },
        update(records, mode, permitted) {
            const device = ["keyboard", "haply"].includes(mode) ? mode : "gamepad";
            const role = robot.id.split(":").at(-1);
            recording = records.find(item => robot.simulation && robot.kind === `${item.environment}-sim`
                && item.device === device && item.streams.includes(role));
            allowed = permitted;
            control.hidden = !recording || !permitted;
            control.disabled = active;
            control.title = recording ? `Replay ${device} inputs · ${recording.task}` : "Replay inputs";
            if (active && (!allowed || !recording)) stop(false,
                !allowed ? "control no longer available" : "recording selection changed");
        },
        stop,
        destroy() { disposed = true; clearInterval(timer); stop(); },
    };
}
