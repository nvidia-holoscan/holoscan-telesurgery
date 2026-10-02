// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { $, element, action, codecName } from "./ui.js";

const formats = {
    MJPG: "MJPEG · compressed",
    JPEG: "JPEG · compressed",
    YUYV: "YUYV · uncompressed",
    UYVY: "UYVY · uncompressed",
    NV12: "NV12 · uncompressed",
    YU12: "I420 · uncompressed",
    YV12: "YV12 · uncompressed",
    RGB3: "RGB · uncompressed",
    BGR3: "BGR · uncompressed",
    GREY: "Grayscale · 8-bit",
};
const size = (mode) => `${mode.width}x${mode.height}`;
const fpsLabel = (fps) => `${Number(Number(fps).toFixed(2))} FPS`;

export function streamSettings(changed) {
    const dialog = $("#stream-dialog"),
        resolution = $("#stream-resolution"),
        fps = $("#stream-fps"),
        format = $("#stream-format"),
        start = $("#start-stream");
    let camera,
        modes,
        busy = false;
    function options(select, values, label, preferred) {
        select.replaceChildren(
            ...values.map((value) => {
                const option = element("option", label(value));
                option.value = value;
                return option;
            }),
        );
        if (values.map(String).includes(String(preferred)))
            select.value = preferred;
        select.disabled = values.length < 2;
    }
    function updateFormat() {
        const previous = format.value || camera.pixel_format || "";
        const available = modes.filter(
            (m) =>
                size(m) === resolution.value &&
                m.fps.includes(Number(fps.value)),
        );
        options(
            format,
            [...new Set(available.map((m) => m.pixel_format || ""))],
            (value) =>
                formats[value] ||
                value ||
                (camera.kind === "HSB" ? "Bayer · 10-bit" : "Device native"),
            previous,
        );
        updateEncoder();
    }
    function updateEncoder() {
        const codec = $("#stream-codec").value,
            jpeg = codec === "nvjpeg",
            raw = codec === "raw-bgr8";
        $("#stream-encoder").hidden = raw;
        $("#stream-qp-field").hidden = jpeg;
        $("#stream-quality").disabled = jpeg;
        $("#stream-jpeg-field").hidden = !jpeg;
        $("#stream-jpeg-quality").disabled = !jpeg;
        $("#stream-speed-field").hidden = jpeg;
        $("#stream-quality-note").textContent = jpeg
            ? "Higher JPEG quality uses more bandwidth."
            : "Lower QP gives higher quality and uses more bandwidth. Slower presets use more GPU time.";
        const [width, height] = resolution.value.split("x").map(Number);
        $("#stream-viewing").textContent = raw
            ? `View in Holoviz. Raw BGR8 needs about ${((width * height * Number(fps.value) * 24) / 1e9).toFixed(2)} Gbit/s per viewer, before transport overhead. No stream compression.${["MJPG", "JPEG"].includes(format.value) ? " Camera capture is still JPEG-compressed." : ""}`
            : codec === "h264"
              ? "View in the browser or Holoviz."
              : "View in Holoviz. Browser preview is unavailable for this codec.";
        $("#stream-summary").textContent =
            `${resolution.selectedOptions[0].textContent} · ${fpsLabel(fps.value)} · ${codecName(codec)}`;
    }
    $("#stream-codec").onchange = updateEncoder;
    function updateRates(preferred = fps.value) {
        const available = modes.filter((m) => size(m) === resolution.value);
        options(
            fps,
            [...new Set(available.flatMap((m) => m.fps))].sort(
                (a, b) => b - a,
            ),
            fpsLabel,
            preferred,
        );
        updateFormat();
    }
    resolution.onchange = () => updateRates();
    fps.onchange = updateFormat;
    $("#cancel-stream").onclick = () => dialog.close();
    dialog.addEventListener("cancel", (event) => {
        if (busy) event.preventDefault();
    });
    $("#stream-form").onsubmit = async (event) => {
        event.preventDefault();
        if (busy) return;
        busy = true;
        start.disabled = true;
        $("#cancel-stream").disabled = true;
        $("#stream-error").hidden = true;
        try {
            const [width, height] = resolution.value.split("x").map(Number);
            const codec = $("#stream-codec").value;
            await action("camera.start", {
                id: camera.id,
                settings: {
                    width,
                    height,
                    fps: Number(fps.value),
                    pixel_format: format.value,
                    codec,
                    ...(codec === "raw-bgr8"
                        ? {}
                        : codec === "nvjpeg"
                          ? {
                                jpeg_quality: Number(
                                    $("#stream-jpeg-quality").value,
                                ),
                            }
                          : {
                                qp: Number($("#stream-quality").value),
                                encoder_preset: $("#stream-preset").value,
                            }),
                },
            });
            dialog.close();
            await changed();
        } catch (error) {
            $("#stream-error").textContent = error.message;
            $("#stream-error").hidden = false;
        } finally {
            busy = false;
            start.disabled = false;
            $("#cancel-stream").disabled = false;
        }
    };
    return (item) => {
        camera = item;
        modes = item.modes?.length
            ? item.modes
            : [
                  {
                      width: item.width,
                      height: item.height,
                      fps: [item.fps],
                      pixel_format: item.pixel_format || "",
                  },
              ];
        $("#stream-camera").textContent = item.name;
        $("#stream-quality").value = item.qp ?? 24;
        $("#stream-jpeg-quality").value = item.jpeg_quality ?? 85;
        options(
            $("#stream-codec"),
            item.codecs || ["h264", "raw-bgr8"],
            (value) =>
                value === "raw-bgr8"
                    ? "Uncompressed · BGR8"
                    : value === "nvjpeg"
                      ? "JPEG · nvJPEG"
                      : `${codecName(value)} · NVENC`,
            item.codec || "h264",
        );
        $("#stream-preset").value = item.encoder_preset || "P1";
        $("#stream-encoder").open = false;
        $("#stream-error").hidden = true;
        $("#stream-mode-note").textContent = item.modes?.length
            ? "Only supported capture modes are shown. Your choice is remembered for Stream all."
            : "Using the configured camera mode. This source does not report additional modes.";
        format.replaceChildren();
        const sizes = [
            ...new Map(modes.map((m) => [size(m), m])).values(),
        ].sort((a, b) => b.width * b.height - a.width * a.height);
        options(
            resolution,
            sizes.map(size),
            (value) => value.replace("x", " × "),
            size(item),
        );
        updateRates(item.fps);
        dialog.showModal();
    };
}
