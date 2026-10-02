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
import { robotControls } from "./robots.js";
import { viewingLayout } from "./workspace.js";
import { metricsPanel } from "./metrics-panel.js";
import { frameTiming } from "./frame-timing.js";
import { streamSettings } from "./stream-settings.js";
import { nodeSettings } from "./node-settings.js";
import { setIcon } from "./icons.js";

for (const control of document.querySelectorAll("[data-icon]"))
    setIcon(control, control.dataset.icon);
for (const dialog of document.querySelectorAll("dialog[data-dismiss-outside]"))
    dismissOnBackdrop(dialog);

let state,
    refreshing = false,
    changingCameras = false,
    robotId = null,
    roleInitialized;
const tiles = new Map(),
    previews = new Set(),
    rendered = new Map();
const layout = viewingLayout();
const metrics = metricsPanel($("#metrics-page"), tiles);
const configureNode = nodeSettings(refresh);
const patient = patientPages(
    () => renderCurrent(),
    configureNode.open,
    configureNode.remove,
    configureNode.environment,
);
const robots = robotControls(refresh, openMetrics);
const configureStream = streamSettings(refresh);
function openMetrics(device) {
    const data = inventory();
    const item = [...(data.cameras || []), ...(data.robots || [])].find(
        (item) => item.id === device,
    );
    metrics.open({ device, title: item?.name || "Metrics" });
}
function renderChanged(name, value, render) {
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
    await action(native ? "view.holoviz" : "view.browser", { camera: id });
    if (state.role === "patient" && !native) previews.add(id);
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
    const enlarge = button(
        "Enlarge",
        () => {
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
    controls.append(enlarge);
    controls.append(
        button("Open in Holoviz", () => displayCamera(camera.id, true)),
    );
    if (state.role === "surgeon")
        controls.append(
            button(
                "Hide",
                () => selectCamera(camera.id, false),
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
    tile.append(video, caption);
    if (state.role === "surgeon") layout.attach(tile, camera);
    $("#videos").append(tile);
    const peer = new RTCPeerConnection({ iceServers: [] });
    tiles.set(camera.id, {
        tile,
        peer,
        title,
        timing: frameTiming(peer, video),
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
    if (!list.length && state.simulation?.status === "loading") {
        for (const name of state.simulation.cameras || [])
            cameras.append(
                device(name, "Available when the room is ready", "loading"),
            );
        return;
    }
    if (!list.length)
        cameras.append(
            element(
                "p",
                state.simulation?.status === "error"
                    ? "Simulation stopped before cameras became available."
                    : state.simulation
                      ? "Loading simulation camera inventory."
                      : state.role === "patient"
                        ? "Discovering connected cameras. Add a node to include its devices."
                        : "No cameras are available yet.",
            ),
        );
    for (const camera of list) {
        const card = device(
            camera.name,
            `${camera.kind} · ${camera.width} × ${camera.height} · ${Number(Number(camera.fps || 0).toFixed(2))} FPS · ${codecName(camera.codec)}`,
            camera.status,
        );
        const identity = element("div", undefined, "camera-identity");
        identity.append(...card.childNodes);
        card.append(identity);
        const controls = element("div", undefined, "actions");
        if (state.role === "patient") {
            const active = ["live", "starting", "stale"].includes(
                camera.status,
            );
            const stream = button(
                active ? "Stop" : "Stream",
                async () => {
                    if (active) {
                        await action("camera.stop", { id: camera.id });
                        await refresh();
                    } else configureStream(camera);
                },
                active ? "secondary small" : "small",
            );
            stream.classList.add("camera-stream");
            stream.disabled =
                !active &&
                (camera.status === "offline" || camera.codecs?.length === 0);
            controls.append(stream);
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
                browserCamera(camera) &&
                (state.selected || []).includes(camera.id);
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
                    else previews.add(camera.id);
                    renderCurrent();
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
        display.disabled = !["live", "stale"].includes(camera.status);
        controls.append(display);
        if (state.native_views?.[camera.id]?.error)
            card.append(element("p", state.native_views[camera.id].error));
        card.append(controls);
        if (camera.error) card.append(element("p", camera.error));
        cameras.append(card);
        if (state.role === "surgeon")
            card.hidden = !camera.name
                .toLowerCase()
                .includes($("#camera-search").value.toLowerCase());
    }
}
function renderSurgeons(data) {
    const list = $("#surgeons");
    list.replaceChildren();
    const requests = (data.surgeons || []).filter(
        (s) => s.status === "pending",
    ).length;
    $("#request-count").hidden = !requests;
    $("#request-count").textContent = `${requests} pending`;
    if (!data.surgeons?.length)
        list.append(element("p", "Surgeon requests will appear here."));
    for (const surgeon of data.surgeons || []) {
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
        card.append(controls);
        list.append(card);
    }
}

function renderCurrent() {
    if (!state) return;
    const isPatient = state.role === "patient",
        approved = state.session?.status === "approved";
    document.body.dataset.role = state.role;
    $("#role").textContent = isPatient ? "Patient" : "Surgeon";
    $("#sdk").textContent = `SDK ${String(state.sdk).split(".")[0]}`;
    $("#connection").textContent = isPatient
        ? "Room online"
        : state.session?.status || "disconnected";
    $("#connection").dataset.status = isPatient
        ? "online"
        : state.session?.status;
    $("#subtitle").textContent = isPatient
        ? `Patient endpoint · port ${state.endpoint_port}`
        : state.patient || "Local surgeon service";
    $("#patient-nav").hidden = !isPatient;
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
        if (!isPatient) $("#feed-list").append($("#cameras"));
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
    const bulk = bulkCameras();
    $("#all-cameras").textContent = bulk.stop ? "Stop all" : "Stream all";
    $("#all-cameras").disabled = changingCameras || !bulk.cameras.length;
    const cameras = data.cameras || [];
    renderChanged(
        "cameras",
        [
            cameras.map(({ frames, ...c }) => c),
            state.selected,
            [...previews],
            state.simulation?.status,
            Object.entries(state.native_views || {}).map(([id, view]) => [
                id,
                view.status,
                view.error,
            ]),
        ],
        () => renderCameras(data),
    );
    let robotList = data.robots || [];
    const picker = $("#robot-selector"),
        options = JSON.stringify(robotList.map(({ id, name }) => [id, name]));
    if (picker.dataset.options !== options) {
        picker.replaceChildren(
            ...robotList.map((r) => new Option(r.name, r.id)),
        );
        picker.dataset.options = options;
    }
    if (!robotList.some((r) => r.id === robotId)) robotId = robotList[0]?.id;
    picker.value = robotId || "";
    $("#robot-choice").hidden = isPatient || robotList.length < 2;
    if (!isPatient) robotList = robotList.filter((r) => r.id === robotId);
    $("#robots-panel").hidden =
        !robotList.length ||
        (!isPatient && (!approved || !state.session.robot));
    $("#robots-panel h2").textContent = isPatient ? "Robots" : "Robot control";
    robots.update(state, { robots: robotList });
    const selectedRobot = robotList[0];
    $("#control-summary").textContent =
        !isPatient && approved && state.session.robot && selectedRobot
            ? `${selectedRobot.name} · ${selectedRobot.owner ? `Control: ${selectedRobot.owner}` : "Control available"}`
            : "";
    const shown = cameras.filter(
        (c) =>
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
        !$("#robots-panel").hidden,
    );
    $("#empty-video").hidden = tiles.size + nativeCameras.length > 0;
    $("#empty-add-feeds").hidden = isPatient;
    $("#stream-count").textContent =
        `${tiles.size} browser${nativeCameras.length ? ` · ${nativeCameras.length} Holoviz` : ""}`;
    $("#hide-all").disabled = !state.selected?.length;
    $("#show-all").disabled = !cameras.some((c) =>
        ["live", "stale"].includes(c.status),
    );
    if (!isPatient) layout.update(state);
}
async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
        state = await api("/api/status");
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
    await robots.releaseAll();
    robotId = event.target.value;
    renderCurrent();
};
function feeds() {
    robots.releaseAll();
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

setInterval(refresh, 1000);
refresh();
