# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# /// script
# requires-python = ">=3.12"
# dependencies = ["matplotlib==3.10.8"]
# ///

"""Regenerate the benchmark SVGs: uv run benchmarks/plot.py."""

import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import MaxNLocator

ROOT = Path(__file__).resolve().parent
SOURCES = (
    ("mira-host", "procedure", "x86", "MIRA Procedure Camera"),
    ("mira-host", "room", "x86", "MIRA Room Camera"),
    ("brio-host", "usb-1e29b43c150f", "x86", "Logitech BRIO Camera"),
    ("imx274-thor", "hsb-192.168.0.2-0", "Thor", "IMX274 Camera"),
    ("mira-spark", "procedure", "DGX Spark", "MIRA Procedure Camera"),
    ("mira-spark", "room", "DGX Spark", "MIRA Room Camera"),
)
CODECS = (("raw-bgr8", "BGR8"), ("nvjpeg", "nvJPEG"), ("h264", "H.264"), ("h265", "H.265"))
RESOLUTIONS = (("1920", "FHD"), ("2560", "QHD"), ("3840", "4K"))
PERCENTILES = (("p50", "P50"), ("p95", "P95"), ("p99", "P99"), ("p99_9", "P99.9"))
COMPONENTS = (
    ("Encode", "#65a30d"),
    ("Transport", "#2563eb"),
    ("Decode", "#7e22ce"),
    ("Other", "#94a3b8"),
)


def save_figure(fig, path):
    fig.savefig(
        path,
        bbox_inches="tight",
        pad_inches=0.03,
        metadata={"Date": None, "Creator": "benchmarks/plot.py"},
    )
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n")
    plt.close(fig)
    print(path.relative_to(ROOT.parent))


def latency_parts(row, percentile):
    """Use contributions at the total's rank, never independent stage percentiles."""
    encode = "pack_ms" if row["codec"] == "raw-bgr8" else "encode_ms"
    decode = "unpack_ms" if row["codec"] == "raw-bgr8" else "decode_ms"
    if row["receiver"] == "webrtc":
        decode = "browser_decode_ms"
    names = (encode, "transport_ms", decode)
    stages = row["stages"]
    parts = [stages[name][percentile] for name in names]
    parts.append(sum(values[percentile] for name, values in stages.items() if name not in names))
    total = float(row[f"total_ms_{percentile}"])
    if any(not math.isfinite(value) or value < 0 for value in parts) or not math.isclose(
        sum(parts), total, rel_tol=1e-9, abs_tol=1e-8
    ):
        raise ValueError(f"Invalid matched-frame breakdown: {row['result']} / {row['camera']}")
    return parts


def load_measurements():
    def key(row):
        return tuple(
            row[name]
            for name in ("sdk", "source", "camera", "width", "height", "codec", "receiver")
        )

    stages = defaultdict(dict)
    with (ROOT / "results" / "stages.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            stages[key(row)][row["stage"]] = {p: float(row[p]) for p, _ in PERCENTILES}
    with (ROOT / "results" / "summary.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["stages"] = stages[key(row)]
        for percentile, _ in PERCENTILES:
            latency_parts(row, percentile)
    return rows


def plot_stream(rows, sdk, source, camera, receiver):
    """Stack matched-frame contributions; sdk=None pairs SDK 5 and SDK 4."""
    stream = [
        row
        for row in rows
        if (row["source"], row["camera"], row["receiver"]) == (source, camera, receiver)
    ]
    native = receiver == "holoviz"
    compare = sdk is None
    sdks = ("5", "4") if compare else (sdk,)
    measured = {
        (row["sdk"], row["codec"], row["width"]): row for row in stream if row["sdk"] in sdks
    }
    resolutions = [
        (width, name) for width, name in RESOLUTIONS if any(width == key[2] for key in measured)
    ]
    fig, axes = (
        plt.subplots(
            4, len(resolutions), figsize=(13.6, 10.8) if compare else (12.8, 10), squeeze=False
        )
        if native
        else plt.subplots(2, 2, figsize=(10.5, 7.6) if compare else (10.5, 7.1))
    )
    fig.subplots_adjust(
        left=0.055,
        right=0.975,
        bottom=0.17 if compare and not native else 0.12,
        top=0.91 if native else 0.885,
        hspace=0.6,
        wspace=0.32 if compare else 0.48,
    )
    receiver_label = "Holoviz" if native else "WebRTC · H.264"
    fig.text(
        0.975,
        0.984,
        f"{'SDK 5 EA3 / SDK 4' if compare else ('SDK 5 EA3' if sdk == '5' else 'SDK 4')}"
        f" · {receiver_label}",
        ha="right",
        va="top",
        fontsize=11,
        color="#526171",
    )

    for column, (group, title) in enumerate(resolutions if native else (("h264", "H.264"),)):
        if native:
            points = [
                (index, name, [measured[version, codec, group] for version in sdks])
                for index, (codec, name) in enumerate(CODECS)
                if (sdks[0], codec, group) in measured
            ]
            group_rows = [row for row in stream if row["width"] == group]
        else:
            points = [
                (index, name, [measured[version, group, width] for version in sdks])
                for index, (width, name) in enumerate(resolutions)
            ]
            group_rows = stream
        for row_index, (percentile, percentile_name) in enumerate(PERCENTILES):
            axis = axes[row_index, column] if native else axes.flat[row_index]
            limit = max(float(row["total_ms_p99_9"]) for row in group_rows) * 1.2
            for sdk_index, _ in enumerate(sdks):
                offset = (-0.18 if sdk_index == 0 else 0.18) if compare else 0
                positions = [index + offset for index, _, _ in points]
                breakdowns = [latency_parts(pair[sdk_index], percentile) for _, _, pair in points]
                bottom = [0.0] * len(points)
                for component, (name, color) in enumerate(COMPONENTS):
                    values = [parts[component] for parts in breakdowns]
                    bars = axis.bar(
                        positions,
                        values,
                        bottom=bottom,
                        width=0.3 if compare else 0.62,
                        label=name if sdk_index == 0 else "_nolegend_",
                        color=color,
                    )
                    bottom = [base + value for base, value in zip(bottom, values, strict=True)]
                if not compare:
                    axis.bar_label(
                        bars,
                        labels=[f"{total:.2f}" for total in bottom],
                        padding=3,
                        fontsize=8,
                        color="#334155",
                    )
            if compare:
                for index, _, pair in points:
                    totals = [float(row[f"total_ms_{percentile}"]) for row in pair]
                    axis.annotate(
                        " / ".join(f"{total:.2f}" for total in totals),
                        (index, max(totals)),
                        xytext=(0, 4),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7.5,
                        color="#334155",
                    )
            axis.set_xticks([index for index, _, _ in points], [name for _, name, _ in points])
            axis.set_xlim(-0.55, points[-1][0] + 0.55)
            axis.set_ylim(0, limit)
            axis.yaxis.set_major_locator(MaxNLocator(nbins=3))
            axis.ticklabel_format(axis="y", style="plain", useOffset=False)
            axis.set_axisbelow(True)
            axis.grid(axis="y", color="#e2e8f0", linewidth=0.8)
            axis.tick_params(length=0, pad=5, labelsize=10)
            if compare:
                axis.set_xticks(
                    [index + offset for index, _, _ in points for offset in (-0.18, 0.18)],
                    [f"{name} (SDK{version})" for _, name, _ in points for version in sdks],
                    rotation=45,
                    ha="right",
                )
                axis.tick_params(axis="x", pad=3, labelsize=8)
            axis.spines[["top", "right", "left"]].set_visible(False)
            axis.spines["bottom"].set_color("#cbd5e1")
            metric_label = f"{percentile_name} total (ms)"
            if not native:
                axis.set_title(metric_label, loc="left", fontsize=12, weight="bold", pad=12)
            elif column == 0:
                axis.set_ylabel(metric_label, labelpad=12, fontsize=11, weight="bold")
        if native:
            axes[0, column].set_title(title, fontsize=13, weight="bold", pad=14)

    fig.legend(
        *axes[0, 0].get_legend_handles_labels(),
        loc="upper left",
        bbox_to_anchor=(0, 1),
        borderaxespad=0,
        ncol=4,
        frameon=False,
        handlelength=2.8,
        columnspacing=2.5,
        fontsize=11,
    )
    fig.text(
        0,
        0.044,
        (
            "Bars: SDK 5 EA3 (left), SDK 4 (right). Total labels: SDK 5 / SDK 4 (ms). "
            "Percentile rows share a scale within each resolution."
            if compare
            else "FHD 1920×1080  ·  QHD 2560×1440  ·  4K 3840×2160. "
            "Latency rows share a scale within each resolution, matched across SDKs."
        ),
        fontsize=9,
    )
    fig.text(
        0,
        0.027,
        "Stacks sum to the labeled total. Contributions follow the total's percentile rank; "
        "they are not independent stage percentiles.",
        fontsize=9,
    )
    fig.text(
        0,
        0.010,
        (
            "BGR8: Encode = pack; Decode = upload. Other = preparation, queues and display handoff."
            if native
            else "Other includes browser delivery/playout; Transport ends at the surgeon service."
        ),
        fontsize=9,
        color="#526171",
    )
    suffix = "" if native else "-webrtc"
    prefix = "sdk-comparison" if compare else f"sdk{sdk}"
    save_figure(fig, ROOT / "figures" / f"{prefix}-{source}-{camera}{suffix}.svg")


def plot_comparison(rows):
    """Compare P99 for matching camera, resolution and codec measurements."""
    measured = {
        (row["sdk"], row["source"], row["camera"], row["width"], row["codec"]): row
        for row in rows
        if row["receiver"] == "holoviz"
    }
    columns = [
        (width, codec, label)
        for width, _ in RESOLUTIONS
        for codec, label in CODECS
        if codec != "h265" or width == "3840"
    ]
    values = []
    for source, camera, _, _ in SOURCES:
        changes = []
        for width, codec, _ in columns:
            pair = [measured.get((sdk, source, camera, width, codec)) for sdk in ("4", "5")]
            changes.append(
                100 * (float(pair[1]["total_ms_p99"]) / float(pair[0]["total_ms_p99"]) - 1)
                if all(pair)
                else math.nan
            )
        values.append(changes)

    fig, axis = plt.subplots(figsize=(13, 4.6))
    fig.subplots_adjust(left=0.21, right=0.97, bottom=0.30, top=0.9)
    largest = max(abs(value) for row in values for value in row if math.isfinite(value))
    scale = max(10, math.ceil(largest / 10) * 10)
    cmap = plt.get_cmap("PuOr_r").copy()
    cmap.set_bad("#e2e8f0")
    colors = axis.imshow(values, cmap=cmap, norm=TwoSlopeNorm(0, -scale, scale), aspect="auto")
    axis.set_xticks(range(len(columns)), [label for _, _, label in columns], fontsize=10)
    axis.set_yticks(
        range(len(SOURCES)),
        [f"{host} · {label.removesuffix(' Camera')}" for _, _, host, label in SOURCES],
        fontsize=10,
    )
    axis.tick_params(length=0, pad=8)
    axis.spines[:].set_visible(False)
    for row, changes in enumerate(values):
        for column, value in enumerate(changes):
            axis.text(
                column,
                row,
                (f"{value:+.0f}%" if round(value) else "0%") if math.isfinite(value) else "—",
                ha="center",
                va="center",
                fontsize=11,
                color="white" if abs(value) > scale * 0.65 else "#17212e",
            )
    for center, name in ((1, "FHD"), (4, "QHD"), (7.5, "4K")):
        axis.text(center, -0.8, name, ha="center", weight="bold", fontsize=12)
    for boundary in (2.5, 5.5):
        axis.axvline(boundary, color="white", linewidth=3)
    colorbar = fig.colorbar(
        colors, cax=fig.add_axes((0.21, 0.12, 0.76, 0.025)), orientation="horizontal"
    )
    ticks = [-scale, -scale / 2, 0, scale / 2, scale]
    colorbar.set_ticks(ticks, labels=[f"{tick:+g}%" if tick else "0%" for tick in ticks])
    colorbar.outline.set_visible(False)
    fig.text(0.21, 0.18, "Lower latency on SDK 5 EA3", fontsize=10)
    fig.text(0.97, 0.18, "Higher latency on SDK 5 EA3", fontsize=10, ha="right")
    fig.text(
        0,
        0.025,
        "Change = (SDK 5 EA3 / SDK 4 − 1) × 100. Gray = not tested. "
        "Separate runs and application revisions.",
        fontsize=9,
        color="#526171",
    )
    path = ROOT / "figures" / "sdk-comparison.svg"
    save_figure(fig, path)


def main():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "text.color": "#334155",
            "axes.labelcolor": "#334155",
            "xtick.color": "#334155",
            "ytick.color": "#64748b",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "svg.hashsalt": "telesurgery-benchmarks",
        }
    )
    rows = load_measurements()
    (ROOT / "figures").mkdir(exist_ok=True)
    for sdk in ("5", "4"):
        for source, camera, *_ in SOURCES:
            for receiver in ("holoviz", "webrtc"):
                plot_stream(rows, sdk, source, camera, receiver)
    for source, camera, *_ in SOURCES:
        for receiver in ("holoviz", "webrtc"):
            plot_stream(rows, None, source, camera, receiver)
    plot_comparison(rows)


if __name__ == "__main__":
    main()
