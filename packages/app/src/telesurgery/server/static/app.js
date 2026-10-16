// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import {
    $,
    element,
    button,
    notice,
    api,
    action,
    device,
    codecName,
    browserCamera,
    dismissOnBackdrop,
} from "./ui.js";
import { patientPages } from "./patient.js";
import { robotControls, robotLabel } from "./robots.js";
import { viewingLayout } from "./workspace.js";
import { metricsPanel } from "./metrics-panel.js";
import { frameTiming } from "./frame-timing.js";
import { streamSettings } from "./stream-settings.js";
import { nodeSettings } from "./node-settings.js";
import { setIcon } from "./icons.js";
import { openLog } from "./logs.js";
import { depthView, nativeDepthControls } from "./depth.js";
import { equipmentTable } from "./equipment.js";
import { feedStrip } from "./feeds.js";
import { motionValues } from "./robot-input.js";
import { setThemeRole } from "./theme.js";
import { viewZoom, cameraZoom } from "./view-zoom.js";

for (const control of document.querySelectorAll("[data-icon]"))
    setIcon(control, control.dataset.icon);
for (const dialog of document.querySelectorAll("dialog[data-dismiss-outside]"))
    dismissOnBackdrop(dialog);

let state,
    refreshing = false,
    changingCameras = false,
    changingWorkspace = false,
    switchingRobot = false,
    changingController = false,
    robotId = null,
    preferredRobot = null,
    robotPreferenceKey,
    roleInitialized;
const roomActions = new Set();
for (const [selector, method, done] of [
    ["#stop-all-streams", "camera.stop_all", "Streams stopped"],
    [
        "#disconnect-all-robots",
        "robot.disconnect_all",
        "Robot connections released",
    ],
]) {
    $(selector).onclick = async () => {
        if (roomActions.size) return;
        roomActions.add(method);
        const output = $("#room-action-status");
        output.hidden = false;
        output.textContent = "Working across all nodes…";
        renderCurrent();
        try {
            const result = await action(method);
            output.textContent = result.failed.length
                ? `${result.completed.length} completed. Not confirmed: ${result.failed.map((item) => `${item.name}: ${item.error}`).join("; ")}`
                : `${done} across all nodes.`;
            output.dataset.error = String(result.failed.length > 0);
        } catch (error) {
            output.textContent = error.message;
            output.dataset.error = "true";
        } finally {
            roomActions.delete(method);
            output.append(
                button(
                    "Dismiss",
                    () => {
                        output.hidden = true;
                    },
                    "text-link",
                ),
            );
            await refresh();
        }
    };
}
const tiles = new Map(),
    previews = new Set(),
    rendered = new Map();
const layout = viewingLayout();
const metrics = metricsPanel($("#metrics-page"), tiles);
const configureNode = nodeSettings(refresh);
const patient = patientPages(
    () => renderCurrent(),
    configureNode.remove,
    refresh,
);
const robots = robotControls(refresh, openMetrics);
const nativeControllerOpen = () => ["starting", "running"].includes(state?.native_controller?.status);
const controllerPreferences = () => Object.fromEntries([...motionValues].filter(([key]) =>
    [":arm-speed", ":roll-speed", ":grip-speed"].some(suffix => key.endsWith(suffix))));
let restoredController, controllerStateInitialized = false;
let controllerGeneration = 0;
function restoreRobotPreference() {
    if (state.role === "patient") return;
    const key = `telesurgery-robot:${state.patient || "local"}`;
    if (robotPreferenceKey === key) return;
    robotPreferenceKey = key;
    robotId = preferredRobot = null;
    try { preferredRobot = localStorage.getItem(key); } catch {}
}
function rememberRobot(id) {
    robotId = preferredRobot = id;
    if (id && robotPreferenceKey) {
        try { localStorage.setItem(robotPreferenceKey, id); } catch {}
    }
}
async function transferController(native) {
    if (changingController) return;
    changingController = true;
    controllerGeneration++;
    const id = robotId;
    let transferred = false;
    try {
        if (native) {
            const retain = await robots.prepareHandoff(id);
            await action("controller.open", {
                id, preferences: controllerPreferences(), input: robots.inputSelection(id),
                retain_control: retain,
            });
            transferred = true;
        } else {
            const result = await action("controller.close", {retain_control: true});
            state.native_controller = result?.controller || {...state.native_controller, status: "closed"};
            if (result?.robot) {
                rememberRobot(result.robot);
                robots.acceptHandoff(result.robot, result.state);
            }
        }
    } catch (error) {
        if (native) await robots.recoverHandoff(id);
        throw error;
    } finally {
        if (native) robots.finishHandoff(id, transferred);
        controllerGeneration++;
        changingController = false;
    }
}
async function acceptReturnedControl(native) {
    changingController = true;
    controllerGeneration++;
    try {
        // A window-manager close returns an existing lease. Never acquire a
        // different robot or resurrect a lease that expired while the web was away.
        const result = await action("controller.close", {retain_control: true, generation: native.generation});
        if (result?.controller) state.native_controller = result.controller;
        if (result?.robot) {
            rememberRobot(result.robot);
            robots.acceptHandoff(result.robot, result.state);
        }
    } catch (error) {
        notice(error);
    } finally {
        controllerGeneration++;
        changingController = false;
        renderCurrent();
    }
}
$("#native-controller").onclick = async () => {
    const control = $("#native-controller");
    control.disabled = true;
    try {
        await transferController(!nativeControllerOpen());
        await refresh();
    } catch (error) {
        notice(error);
    } finally {
        renderCurrent();
    }
};
const equipment = equipmentTable(
    renderCurrent,
    cameraCard,
    robots.patientActions,
);
const configureStream = streamSettings(refresh);
const quickFeeds = feedStrip(selectCamera, displayCamera, closeNative);
async function openMetrics(device) {
    if (document.fullscreenElement?.classList.contains("video-tile"))
        await document.exitFullscreen();
    equipment.close();
    $("#feed-dialog").close();
    const data = inventory();
    const item = [...(data.cameras || []), ...(data.robots || [])].find(
        (item) => item.id === device,
    );
    metrics.open({ device, title: item?.name || "Metrics" });
}
function renderChanged(name, value, render) {
    if (name === "cameras" && document.activeElement?.closest(".camera-zoom")) return;
    const signature = JSON.stringify(value);
    if (rendered.get(name) !== signature) {
        render();
        rendered.set(name, signature);
    }
}
function inventory() {
    return state.role === "patient" ? state : state.session || {};
}
function scopedInventory() {
    const data = inventory();
    if (state.role !== "patient") return data;
    const id = patient.current().node;
    return {
        ...data,
        cameras: (data.cameras || []).filter(
            (c) => (c.node || c.id.split(":")[0]) === id,
        ),
        robots: (data.robots || []).filter(
            (r) => (r.node || r.id.split(":")[0]) === id,
        ),
    };
}
function bulkCameras() {
    const cameras = scopedInventory().cameras || [];
    const active = cameras.filter((c) =>
        ["live", "starting", "stale"].includes(c.status),
    );
    return {
        stop: active.length > 0,
        cameras: active.length
            ? active
            : cameras.filter((c) => ["stopped", "error"].includes(c.status)),
    };
}
function nativeViewing(id) {
    return ["starting", "running"].includes(state.native_views?.[id]?.status);
}
async function displayCamera(id, native) {
    await tiles.get(id)?.zoom?.flush();
    await action(native ? "view.holoviz" : "view.browser", { camera: id });
    if (state.role === "patient") {
        equipment.close();
        if (!native) previews.add(id);
    }
    await refresh();
}
async function closeNative(id) {
    await action("view.close", { camera: id });
    await refresh();
}

async function openVideo(camera) {
    if (tiles.has(camera.id)) return;
    const tile = element("div", undefined, "video-tile");
    tile.dataset.camera = camera.id;
    const video = document.createElement("video");
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    const caption = element("div", undefined, "video-caption");
    const title = element("strong", camera.name);
    title.title = camera.name;
    const controls = element("div", undefined, "actions");
    const patientPreview = state.role === "patient";
    const enlarge = button(
        patientPreview ? "Fullscreen" : "Enlarge",
        async () => {
            if (patientPreview) {
                if (document.fullscreenElement === tile)
                    await document.exitFullscreen();
                else await tile.requestFullscreen();
                return;
            }
            const focused = tile.classList.toggle("focused");
            setIcon(
                enlarge,
                focused ? "collapse" : "expand",
                focused ? "Restore" : "Enlarge",
            );
            enlarge.setAttribute("aria-pressed", String(focused));
        },
        "secondary small icon-button",
        "expand",
    );
    enlarge.setAttribute("aria-pressed", "false");
    if (patientPreview)
        tile.addEventListener("fullscreenchange", () => {
            const expanded = document.fullscreenElement === tile;
            setIcon(
                enlarge,
                expanded ? "collapse" : "expand",
                expanded ? "Exit fullscreen" : "Fullscreen",
            );
            enlarge.setAttribute("aria-pressed", String(expanded));
        });
    controls.append(enlarge);
    controls.append(
        button("Open in Holoviz", () => displayCamera(camera.id, true)),
    );
    controls.append(
        button(
            "Hide",
            () => {
                if (state.role === "surgeon")
                    return selectCamera(camera.id, false);
                previews.delete(camera.id);
                renderCurrent();
            },
            "secondary small icon-button",
            "hide",
        ),
    );
    caption.append(
        title,
        element(
            "small",
            `${camera.kind} · ${camera.width} × ${camera.height} · WebRTC`,
        ),
        controls,
    );
    controls.append(
        button(
            "Metrics",
            () => openMetrics(camera.id),
            "secondary small",
            "chart",
        ),
    );
    const stage = element("div", undefined, "depth-stage");
    stage.append(video);
    const viewport = element("div", undefined, "view-viewport");
    const surface = element("div", undefined, "view-surface");
    video.style.aspectRatio = `${camera.width} / ${camera.height}`;
    viewport.append(stage);
    surface.append(viewport);
    tile.append(surface, caption);
    if (state.role === "surgeon") layout.attach(tile, camera);
    $("#videos").append(tile);
    const peer = new RTCPeerConnection({ iceServers: [] });
    tiles.set(camera.id, {
        tile,
        peer,
        title,
        timing: frameTiming(peer, video),
        depth: depthView(peer, video, stage, caption, camera, state.view_displays?.[camera.id]),
        zoom: viewZoom(camera, { viewport, stage, surface, initial: state.view_zooms?.[camera.id] }),
    });
    peer.ontrack = ({ track }) => {
        video.srcObject = new MediaStream([track]);
    };
    peer.onconnectionstatechange = () => {
        if (peer.connectionState === "failed") {
            closeVideo(camera.id);
            notice("Video connection failed. Select the camera to retry.");
        }
    };
    const transceiver = peer.addTransceiver("video", {
        direction: "recvonly",
    });
    transceiver.setCodecPreferences(
        RTCRtpReceiver.getCapabilities("video").codecs.filter(
            (c) => c.mimeType === "video/H264",
        ),
    );
    try {
        await peer.setLocalDescription(await peer.createOffer());
        if (peer.iceGatheringState !== "complete")
            await new Promise((resolve) => {
                const done = () => {
                    if (peer.iceGatheringState === "complete") {
                        peer.removeEventListener(
                            "icegatheringstatechange",
                            done,
                        );
                        resolve();
                    }
                };
                peer.addEventListener("icegatheringstatechange", done);
                done();
            });
        const answer = await api("/api/offer", {
            camera: camera.id,
            sdp: peer.localDescription.sdp,
            type: peer.localDescription.type,
        });
        if (tiles.get(camera.id)?.peer === peer)
            await peer.setRemoteDescription(answer);
    } catch (error) {
        if (tiles.get(camera.id)?.peer === peer) {
            closeVideo(camera.id);
            notice(error);
        }
    }
}
function closeVideo(id) {
    const item = tiles.get(id);
    if (!item) return;
    tiles.delete(id);
    item.timing.stop();
    item.depth.stop();
    item.zoom.stop();
    item.peer.close();
    item.tile.remove();
}
async function selectCamera(id, show) {
    const selected = new Set(state.selected || []);
    if (show) selected.add(id);
    else selected.delete(id);
    await action("view", { cameras: [...selected] });
    if (!show) closeVideo(id);
    await refresh();
}

function renderCameras(data) {
    const cameras = $("#cameras");
    cameras.replaceChildren();
    const list = data.cameras || [];
    if (!list.length)
        cameras.append(
            element(
                "p",
                state.role === "patient"
                    ? "No cameras are available yet."
                    : "No live streams.",
            ),
        );
    for (const camera of list) cameras.append(cameraCard(camera));
}

function cameraCard(camera) {
    const card = device(
        camera.name,
        `${camera.kind} · ${camera.width} × ${camera.height} · ${Number(Number(camera.fps || 0).toFixed(2))} FPS · ${codecName(camera.codec)}`,
        camera.status,
    );
    const identity = element("div", undefined, "camera-identity");
    identity.append(...card.childNodes);
    if (state.role === "patient") {
        const logs = button(
            "Logs",
            () =>
                openLog(
                    `${camera.name} · Camera log`,
                    `/api/cameras/${encodeURIComponent(camera.id)}/log`,
                ),
            "text-link camera-log",
            "logs",
        );
        logs.setAttribute("aria-label", `${camera.name} camera logs`);
        logs.setAttribute("aria-haspopup", "dialog");
        identity.querySelector(".status").append(logs);
    }
    card.append(identity);
    const controls = element("div", undefined, "actions");
    if (state.role === "patient") {
        const active = ["live", "starting", "stale"].includes(camera.status);
        const stream = button(
            active ? "Stop" : "Stream",
            async () => {
                stream.disabled = true;
                try {
                    await action(active ? "camera.stop" : "camera.start", {
                        id: camera.id,
                    });
                    await refresh();
                } finally {
                    stream.disabled = false;
                }
            },
            active ? "secondary small" : "small",
        );
        stream.classList.add("camera-stream");
        stream.disabled =
            !active &&
            (camera.status === "offline" || camera.codecs?.length === 0);
        controls.append(stream);
        const settings = button(
            "Stream settings",
            () => configureStream(camera),
            "secondary small icon-button camera-settings",
            "settings",
        );
        settings.disabled = stream.disabled;
        settings.title = active
            ? "Change stream encoding"
            : "Stream settings";
        controls.append(settings);
        const heading = element("div", undefined, "camera-name");
        heading.append(
            identity.querySelector("strong"),
            button(
                "Rename",
                async () => {
                    const name = prompt("Camera name", camera.name);
                    if (name?.trim()) {
                        await action("camera.rename", {
                            id: camera.id,
                            name,
                        });
                        await refresh();
                    }
                },
                "secondary small icon-button",
                "rename",
            ),
        );
        identity.prepend(heading);
    } else {
        const shown =
            browserCamera(camera) && (state.selected || []).includes(camera.id);
        const control = button(
            shown ? "Hide" : "Show",
            () => selectCamera(camera.id, !shown),
            "secondary small icon-button",
            shown ? "hide" : "preview",
        );
        control.classList.add("camera-preview");
        control.disabled =
            !browserCamera(camera) ||
            !["live", "stale"].includes(camera.status);
        if (!browserCamera(camera))
            control.title = "Browser viewing requires H.264. Use Holoviz.";
        controls.append(control);
    }
    if (state.role === "patient") {
        const unavailable = !browserCamera(camera)
            ? "Browser preview requires H.264. Use Holoviz."
            : nativeViewing(camera.id)
              ? "Use Show in browser to switch from Holoviz."
              : !["live", "stale"].includes(camera.status)
                ? "Start streaming to preview."
                : "";
        const preview = button(
            !unavailable && previews.has(camera.id)
                ? "Hide preview"
                : "Preview",
            () => {
                if (previews.has(camera.id)) previews.delete(camera.id);
                else {
                    previews.add(camera.id);
                    equipment.close();
                }
                renderCurrent();
                if (previews.has(camera.id))
                    $("#views-panel").scrollIntoView({ block: "nearest" });
            },
            "secondary small icon-button",
            !unavailable && previews.has(camera.id) ? "hide" : "preview",
        );
        preview.classList.add("camera-preview");
        preview.disabled = !!unavailable;
        if (unavailable) preview.title = unavailable;
        controls.append(preview);
    }
    if (state.role === "patient") {
        controls.append(
            button(
                "Metrics",
                () => openMetrics(camera.id),
                "secondary small icon-button camera-metrics",
                "chart",
            ),
        );
    }
    card.dataset.search = camera.name.toLowerCase();
    const native = nativeViewing(camera.id);
    const display = button(
        native
            ? browserCamera(camera)
                ? "Show in browser"
                : "Close Holoviz"
            : "Open in Holoviz",
        () =>
            native && !browserCamera(camera)
                ? closeNative(camera.id)
                : displayCamera(camera.id, !native),
    );
    display.classList.add("camera-display");
    if (state.role === "patient") {
        display.classList.add("secondary", "small", "icon-button");
        setIcon(display, "monitor");
        const logs = button(
            "Camera logs",
            () =>
                openLog(
                    `${camera.name} · Camera log`,
                    `/api/cameras/${encodeURIComponent(camera.id)}/log`,
                ),
            "secondary small icon-button camera-logs",
            "logs",
        );
        controls.append(logs);
    }
    display.disabled = !["live", "stale"].includes(camera.status);
    controls.append(display);
    if (state.native_views?.[camera.id]?.error)
        card.append(element("p", state.native_views[camera.id].error));
    card.append(controls);
    if (state.role === "patient") {
        const zoom = cameraZoom(camera);
        if (zoom) card.append(zoom);
    }
    if (camera.error) card.append(element("p", camera.error));
    if (camera.encoding_error)
        card.append(element("p", camera.encoding_error, "encoding-warning"));
    if (state.role === "surgeon")
        card.hidden = !camera.name
            .toLowerCase()
            .includes($("#camera-search").value.toLowerCase());
    return card;
}

function renderSurgeons(data) {
    const list = $("#surgeons");
    list.replaceChildren();
    const requests = (data.surgeons || []).filter(
        (s) => s.status === "pending",
    ).length;
    $("#request-count").hidden = !requests;
    $("#request-count").textContent = `${requests} pending`;
    function surgeonCard(surgeon) {
        const card = device(
            surgeon.name,
            ["approved", "offline"].includes(surgeon.status)
                ? surgeon.robot
                    ? "Video and robot access"
                    : "View-only access"
                : surgeon.status === "revoked"
                  ? "Access ended"
                  : surgeon.requested_robot
                    ? "Requested video and robot access"
                    : "Requested video access",
            surgeon.status,
        );
        const controls = element("div", undefined, "actions");
        if (surgeon.status === "pending") {
            if (surgeon.requested_robot)
                controls.append(
                    button("Approve robot", async () => {
                        await action("access.approve", {
                            id: surgeon.id,
                            robot: true,
                        });
                        await refresh();
                    }),
                );
            controls.append(
                button("Approve view", async () => {
                    await action("access.approve", {
                        id: surgeon.id,
                        robot: false,
                    });
                    await refresh();
                }),
            );
            controls.append(
                button(
                    "Reject",
                    async () => {
                        await action("access.reject", { id: surgeon.id });
                        await refresh();
                    },
                    "danger small",
                ),
            );
        } else if (["approved", "offline"].includes(surgeon.status)) {
            controls.append(
                button(
                    "Revoke access",
                    async () => {
                        await action("access.revoke", { id: surgeon.id });
                        await refresh();
                    },
                    "danger small",
                ),
            );
        }
        const avatar = element(
            "span",
            surgeon.name
                .split(/\s+/)
                .slice(0, 2)
                .map((part) => part[0])
                .join("")
                .toUpperCase(),
            "surgeon-avatar",
        );
        avatar.setAttribute("aria-hidden", "true");
        card.prepend(avatar);
        card.append(controls);
        return card;
    }
    list.replaceChildren(...(data.surgeons || []).map(surgeonCard));
    const access = $("#overview-access");
    const people = (data.surgeons || [])
        .filter((s) => ["pending", "approved"].includes(s.status))
        .sort(
            (a, b) =>
                Number(b.status === "pending") - Number(a.status === "pending"),
        );
    access.replaceChildren(...people.slice(0, 3).map(surgeonCard));
    if (!people.length)
        access.append(
            element(
                "p",
                "Surgeon requests appear here for your approval.",
                "quiet-state",
            ),
        );
    if (!data.surgeons?.length)
        list.append(
            element("p", "Surgeon requests will appear here.", "quiet-state"),
        );
}

function renderRobots(data, isPatient, approved) {
    let robotList = [...(data.robots || [])].sort(
        (a, b) =>
            a.name.localeCompare(b.name, undefined, {
                numeric: true,
                sensitivity: "base",
            }) || robotLabel(a).localeCompare(robotLabel(b)),
    );
    if (isPatient)
        robotList = robotList.filter((r) => r.id === equipment.selected);
    else {
        robotList = robotList.filter(
            (r) =>
                r.status === "online" &&
                r.connection_enabled !== false &&
                r.node_online !== false,
        );
        if (robotList.some((r) => r.id === preferredRobot))
            robotId = preferredRobot;
    }
    if (!robotList.some((r) => r.id === robotId))
        robotId = isPatient || !preferredRobot ? robotList[0]?.id : null;
    if (!isPatient && robotId && robotId !== preferredRobot) rememberRobot(robotId);
    const available = robotList.length;
    const picker = $("#robot-selector"),
        options = JSON.stringify([
            !robotId,
            robotList.map((r) => [r.id, robotLabel(r)]),
        ]);
    if (picker.dataset.options !== options) {
        picker.replaceChildren(
            ...robotList.map((r) => new Option(robotLabel(r), r.id)),
        );
        if (!robotId) {
            const placeholder = new Option("Select a robot", "");
            placeholder.disabled = true;
            picker.prepend(placeholder);
        }
        picker.dataset.options = options;
    }
    picker.value = robotId || "";
    picker.disabled = switchingRobot || changingController || changingWorkspace;
    $("#robot-choice").hidden = isPatient || !available;
    if (!isPatient) robotList = robotList.filter((r) => r.id === robotId);
    $("#robots-panel").hidden = isPatient
        ? !robotList.length
        : !data.robots?.length || !approved;
    const viewOnly = !isPatient && !state.session?.robot;
    $("#robots-panel h2").textContent =
        isPatient || viewOnly ? "Robots" : "Robot control";
    $("#robots-panel .section-kicker").textContent = isPatient
        ? "NODE DEVICES"
        : viewOnly
          ? "VIEW ONLY"
          : "EXCLUSIVE ACCESS";
    const nativeOpen = nativeControllerOpen();
    $("#native-controller").hidden = isPatient || viewOnly;
    $("#native-controller").disabled = changingController || changingWorkspace || switchingRobot
        || !approved || (!nativeOpen && !robotId);
    $("#native-controller").setAttribute("aria-pressed", String(nativeOpen));
    setIcon($("#native-controller"), nativeOpen ? "dock" : "popout", nativeOpen ? "Dock robot controls" : "Pop out robot controls");
    $("#native-controller-away").hidden = !nativeOpen;
    $("#robots").hidden = nativeOpen;
    if (nativeOpen) $("#robot-choice").hidden = true;
    robots.update(state, {robots: robotList});
    if (!isPatient && !robotList.length)
        $("#robots").replaceChildren(
            element(
                "p",
                available
                    ? "Select a robot above."
                    : "No connected robots. Connect a robot in the patient dashboard.",
                "quiet-state",
            ),
        );
}
function renderCurrent() {
    if (!state) return;
    restoreRobotPreference();
    const native = state.native_controller;
    if (!controllerStateInitialized) {
        controllerStateInitialized = true;
        // A closed window in the initial snapshot is history, not a new dock.
        // Only an outstanding lease handoff needs to be consumed after reload.
        if (native?.status === "closed" && !native.handoff)
            restoredController = native.generation;
    }
    if (native?.status === "closed" && native.generation && native.generation !== restoredController) {
        restoredController = native.generation;
        for (const [key, value] of Object.entries(native.preferences || {}))
            motionValues.set(key, value);
        if (native.robot && state.session?.robots?.some(r => r.id === native.robot))
            rememberRobot(native.robot);
        if ("input" in native) robots.restoreInput(native.robot, native.input);
        robots.rebuild();
        if (native.handoff && !changingController) acceptReturnedControl(native);
    }
    const isPatient = state.role === "patient",
        approved = state.session?.status === "approved";
    setThemeRole(state.role);
    document.body.dataset.role = state.role;
    $("#role").textContent = isPatient ? "Patient" : "Surgeon";
    $("#connection").textContent = isPatient
        ? "Room online"
        : state.session?.status || "disconnected";
    $("#connection").dataset.status = isPatient
        ? "online"
        : state.session?.status;
    $("#subtitle").textContent = isPatient
        ? `Port ${state.endpoint_port}`
        : state.patient || "Local surgeon service";
    $("#patient-nav").hidden = !isPatient;
    $("#patient-stop-actions").hidden = !isPatient;
    $("#stop-all-streams").disabled = roomActions.size > 0;
    $("#disconnect-all-robots").disabled = roomActions.size > 0;
    $("#disconnect").hidden =
        isPatient ||
        ["disconnected", undefined].includes(state.session?.status);
    $("#join").hidden =
        isPatient ||
        !["disconnected", "revoked", undefined].includes(state.session?.status);
    $("#session").hidden = isPatient || state.session?.status !== "pending";
    $("#session-status").textContent =
        "Your request has been sent. Cameras and controls become available after approval.";
    if (roleInitialized !== state.role) {
        roleInitialized = state.role;
        document.title = `Holoscan Telesurgery - ${isPatient ? "Patient" : "Surgeon"}`;
        if (!isPatient) {
            $("#feed-list").append($("#cameras"));
        } else {
            $("#device-detail-body").append(
                $("#camera-panel"),
                $("#robots-panel"),
            );
            $("#equipment-actions").append($("#all-cameras"));
        }
    }
    if (isPatient) {
        patient.update(state);
        renderChanged("surgeons", state.surgeons, () => renderSurgeons(state));
    } else {
        for (const section of document.querySelectorAll("[data-page]"))
            section.hidden = true;
        $("#patient-node-header").hidden = true;
        $("#camera-panel").hidden = true;
        $("#device-workspace").hidden = !approved;
        if (!approved) {
            $("#feed-dialog").close();
            metrics.close();
        }
    }
    const data = scopedInventory();
    const liveCameras = (data.cameras || []).filter((c) =>
        ["live", "stale"].includes(c.status),
    );
    if (!isPatient)
        quickFeeds.update(
            liveCameras,
            state.selected || [],
            state.native_views || {},
        );
    $("#quick-feeds").hidden = isPatient;
    const bulk = bulkCameras();
    $("#all-cameras").textContent = bulk.stop ? "Stop all" : "Stream all";
    $("#all-cameras").disabled = changingCameras || !bulk.cameras.length;
    const cameras = data.cameras || [];
    if (isPatient)
        equipment.update(data, patient.current().node, [
            [...previews],
            state.native_views,
        ]);
    const detailCameras = isPatient
        ? cameras.filter((c) => c.id === equipment.selected)
        : liveCameras;
    renderChanged(
        "cameras",
        [
            detailCameras.map(({ frames, ...c }) => c),
            state.selected,
            [...previews],
            Object.entries(state.native_views || {}).map(([id, view]) => [
                id,
                view.status,
                view.error,
            ]),
        ],
        () => renderCameras({ ...data, cameras: detailCameras }),
    );
    renderRobots(data, isPatient, approved);
    const shown = cameras.filter(
        (c) =>
            changingWorkspace !== "popout" &&
            ["live", "stale"].includes(c.status) &&
            browserCamera(c) &&
            !nativeViewing(c.id) &&
            (isPatient
                ? patient.current().page === "node" && previews.has(c.id)
                : approved && state.selected?.includes(c.id)),
    );
    for (const id of tiles.keys())
        if (!shown.some((c) => c.id === id)) closeVideo(id);
    for (const camera of shown) {
        if (tiles.has(camera.id)) {
            tiles.get(camera.id).title.textContent = camera.name;
            tiles.get(camera.id).title.title = camera.name;
        } else openVideo(camera);
    }
    const nativeCameras = cameras.filter(
        (c) => nativeViewing(c.id) && (isPatient || approved),
    );
    renderChanged(
        "native-tiles",
        nativeCameras.map((c) => [
            c.id,
            c.name,
            state.native_views[c.id].status,
        ]),
        () => {
            $("#native-views").replaceChildren();
            for (const camera of nativeCameras) {
                const tile = device(
                    camera.name,
                    `${codecName(camera.codec)} · Holoviz is open`,
                );
                tile.classList.add("native-tile");
                tile.append(viewZoom(camera, {
                    native: true,
                    initial: state.view_zooms?.[camera.id],
                }).element);
                nativeDepthControls(
                    camera,
                    tile,
                    state.native_views[camera.id].display,
                );
                const controls = element("div", undefined, "actions");
                const metrics = button(
                    "Metrics",
                    () => openMetrics(camera.id),
                    "text-link",
                    "chart",
                );
                metrics.setAttribute(
                    "aria-label",
                    `${camera.name} Holoviz metrics`,
                );
                controls.append(
                    metrics,
                    button(
                        browserCamera(camera)
                            ? "Show in browser"
                            : "Close Holoviz",
                        () =>
                            browserCamera(camera)
                                ? displayCamera(camera.id, false)
                                : closeNative(camera.id),
                    ),
                );
                if (!isPatient && browserCamera(camera))
                    controls.append(
                        button(
                            "Hide",
                            () => selectCamera(camera.id, false),
                            "secondary small icon-button",
                            "hide",
                        ),
                    );
                tile.append(controls);
                $("#native-views").append(tile);
            }
        },
    );
    $("#view-toolbar").hidden = isPatient;
    $("#workspace-kicker").hidden = isPatient;
    $("#workspace-title").textContent = isPatient
        ? "Camera previews"
        : "Live views";
    $("#views-panel").hidden =
        isPatient && tiles.size + nativeCameras.length === 0;
    $("#operating-workspace").classList.toggle(
        "has-robot",
        !isPatient && !$("#robots-panel").hidden,
    );
    if (isPatient) {
        $("#camera-panel").hidden = !detailCameras.length;
    }
    $("#equipment-panel").hidden = !isPatient;
    $("#operating-workspace").hidden =
        isPatient && tiles.size + nativeCameras.length === 0;
    $("#empty-title").textContent = isPatient
        ? "No previews open"
        : liveCameras.length
          ? "Choose your views"
          : "No live streams";
    $("#empty-description").textContent = isPatient
        ? "Start a camera, then open its preview."
        : liveCameras.length
          ? "Select a camera above to start viewing."
          : "Live streams appear when the patient starts a camera.";
    $("#preview-devices").hidden = !isPatient;
    $("#empty-video").hidden = tiles.size + nativeCameras.length > 0;
    $("#empty-add-feeds").hidden = isPatient;
    $("#hide-all").disabled = !state.selected?.length;
    $("#popout-all").disabled =
        changingWorkspace || changingController || switchingRobot ||
        (!selectedPopoutCameras().length && (!currentRobotControl() || nativeControllerOpen()));
    $("#dock-all").disabled =
        changingWorkspace || changingController || switchingRobot ||
        (!nativeControllerOpen() &&
            !Object.keys(state.native_views || {}).some(nativeViewing));
    $("#show-all").disabled = !cameras.some((c) =>
        ["live", "stale"].includes(c.status),
    );
    if (!isPatient) layout.update(state);
}
async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
        let requestedGeneration, next;
        do {
            requestedGeneration = controllerGeneration;
            next = await api("/api/status");
        } while (requestedGeneration !== controllerGeneration);
        // A pre-dock response must not mark the browser's returned lease as
        // ineligible merely because it still describes the native window as open.
        state = next;
        renderCurrent();
    } catch (error) {
        notice(error);
    } finally {
        refreshing = false;
    }
}
$("#join-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    try {
        await action("connect", {
            address: form.get("address"),
            name: form.get("name"),
            robot: form.has("robot"),
        });
        await refresh();
    } catch (error) {
        notice(error);
    }
});
$("#disconnect").addEventListener("click", async () => {
    await robots.releaseAll();
    await action("disconnect");
    await refresh();
});
$("#robot-selector").onchange = async (event) => {
    const selected = event.target.value;
    event.target.value = robotId || "";
    if (switchingRobot || changingController || changingWorkspace || selected === robotId) return;
    switchingRobot = true;
    robots.switching(true);
    renderCurrent();
    try {
        if (robots.hasControl()) {
            const dialog = $("#switch-robot-dialog");
            const next = state.session?.robots?.find(robot => robot.id === selected);
            $("#switch-robot-name").textContent = next ? robotLabel(next) : selected;
            dialog.returnValue = "cancel";
            const confirmed = new Promise(resolve => dialog.addEventListener(
                "close", () => resolve(dialog.returnValue === "switch"), {once: true},
            ));
            dialog.showModal();
            if (!await confirmed) return;
        }
        if (!await robots.releaseAll())
            throw new Error("Control release was not confirmed. Robot selection kept; retry release before switching.");
        rememberRobot(selected);
    } catch (error) {
        notice(error);
    } finally {
        switchingRobot = false;
        robots.switching(false);
        renderCurrent();
    }
};
function feeds() {
    robots.pause("camera selection opened");
    $("#feed-dialog").showModal();
}
$("#add-feeds").onclick = feeds;
$("#empty-add-feeds").onclick = feeds;
$("#close-feeds").onclick = () => $("#feed-dialog").close();
$("#camera-search").oninput = () => {
    for (const card of $("#cameras").children)
        card.hidden = !(card.dataset.search || "").includes(
            $("#camera-search").value.toLowerCase(),
        );
};
$("#all-cameras").onclick = async () => {
    if (changingCameras) return;
    changingCameras = true;
    renderCurrent();
    try {
        const { stop, cameras } = bulkCameras();
        for (const camera of cameras)
            await action(stop ? "camera.stop" : "camera.start", {
                id: camera.id,
            });
    } catch (error) {
        notice(error);
    } finally {
        changingCameras = false;
        await refresh();
    }
};
async function chooseAll(show) {
    try {
        await action("view", {
            cameras: show
                ? (inventory().cameras || [])
                      .filter(
                          (c) =>
                              ["live", "stale"].includes(c.status) &&
                              (browserCamera(c) || nativeViewing(c.id)),
                      )
                      .map((c) => c.id)
                : [],
        });
        await refresh();
    } catch (error) {
        notice(error);
    }
}
$("#show-all").onclick = () => chooseAll(true);
$("#hide-all").onclick = () => chooseAll(false);

function currentRobotControl() {
    return (
        state?.role === "surgeon" &&
        state.session?.robot &&
        state.session.robots?.some(
            (r) =>
                r.id === robotId &&
                r.status === "online" &&
                r.connection_enabled !== false,
        )
    );
}
function selectedPopoutCameras() {
    const selected = new Set(state.selected || []);
    return (inventory().cameras || []).filter(c =>
        selected.has(c.id) && ["live", "stale"].includes(c.status) && !nativeViewing(c.id));
}
async function changeWorkspace(native) {
    if (changingWorkspace) return;
    await Promise.all([...tiles.values()].map(item => item.zoom.flush()));
    const selectedCameras = native ? selectedPopoutCameras() : [];
    changingWorkspace = native ? "popout" : "dock";
    const control = $(native ? "#popout-all" : "#dock-all");
    const icon = native ? "popout" : "dock";
    const label = native ? "Pop out all" : "Dock all";
    $("#popout-all").disabled = $("#dock-all").disabled = true;
    control.setAttribute("aria-busy", "true");
    // Retire browser offers before native viewers claim those streams.
    renderCurrent();
    try {
        const failures = [];
        try {
            if (native && currentRobotControl())
                await transferController(true);
            else if (!native && nativeControllerOpen())
                await transferController(false);
        } catch (error) {
            failures.push(`Robot controls: ${error.message}`);
        }
        await refresh();
        if (document.fullscreenElement) await document.exitFullscreen();
        const inventoryCameras = inventory().cameras || [];
        const cameras = native
            ? selectedCameras
            : Object.keys(state.native_views || {})
                  .filter(nativeViewing)
                  .map(
                      (id) =>
                          inventoryCameras.find((c) => c.id === id) || {
                              id,
                              name: id,
                          },
                  );
        for (const [index, camera] of cameras.entries()) {
            setIcon(
                control,
                icon,
                `${native ? "Opening" : "Docking"} ${index + 1}/${cameras.length}`,
            );
            try {
                const method = native
                    ? "view.holoviz"
                    : browserCamera(camera) &&
                        ["live", "stale"].includes(camera.status)
                      ? "view.browser"
                      : "view.close";
                await action(method, { camera: camera.id });
            } catch (error) {
                failures.push(`${camera.name}: ${error.message}`);
            }
            await refresh();
        }
        if (failures.length) notice(failures.join("; "));
    } catch (error) {
        notice(error);
    } finally {
        changingWorkspace = false;
        control.removeAttribute("aria-busy");
        setIcon(control, icon, label);
        await refresh();
    }
}
$("#popout-all").onclick = () => changeWorkspace(true);
$("#dock-all").onclick = () => changeWorkspace(false);

setInterval(refresh, 1000);
refresh();
