# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Refresh SDK 5 CSVs and report tables from measured records; retain SDK 4 history.

Run ``python benchmarks/report.py``, then ``uv run benchmarks/plot.py``.
"""

import csv
import json
import math
import re
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
PERCENTILES = ("p50", "p95", "p99", "p99_9")
SOURCES = (
    ("mira-host", "procedure", "x86 · MIRA Procedure Camera"),
    ("mira-host", "room", "x86 · MIRA Room Camera"),
    ("brio-host", "usb-1e29b43c150f", "x86 · Logitech BRIO Camera"),
    ("imx274-thor", "hsb-192.168.0.2-0", "Thor · IMX274 Camera"),
    ("mira-spark", "procedure", "DGX Spark · MIRA Procedure Camera"),
    ("mira-spark", "room", "DGX Spark · MIRA Room Camera"),
)
CODECS = {"raw-bgr8": "BGR8", "nvjpeg": "nvJPEG", "h264": "H.264", "h265": "H.265"}


def read_csv(name):
    with (ROOT / "results" / name).open(newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def write_csv(name, fields, rows):
    with (ROOT / "results" / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def records():
    rows, stages, dates = [], [], []
    files = sorted((ROOT / "results/matrix").glob("sdk5-*.json"))
    for filename in files:
        match = re.fullmatch(r"sdk5-(.+)-(\d+)x(\d+)-(.+)-(holoviz|webrtc)", filename.stem)
        if not match:
            continue
        source, width, height, codec, receiver = match.groups()
        data = json.loads(filename.read_text())
        if data["status"] != "measured":
            raise ValueError(f"Unmeasured record: {filename}")
        dates.append(data["finished_utc"][:10])
        for key, stream in data["streams"].items():
            report, path = stream["report"], stream["path"]
            if not path.get("count") or path.get("missing"):
                raise ValueError(f"Incomplete path: {filename} / {key}")
            for percentile in PERCENTILES:
                total = path["total"][percentile]
                parts = [value[percentile] for value in path["stages"].values()]
                if not all(
                    math.isfinite(v) and v >= 0 for v in [total, *parts]
                ) or not math.isclose(sum(parts), total, rel_tol=1e-9, abs_tol=1e-8):
                    raise ValueError(f"Invalid matched stages: {filename} / {key}")
            metrics = report["steady_metrics"]
            source_report = data["source_metrics"][key]
            row = {
                "sdk": "5",
                "source": source,
                "width": width,
                "height": height,
                "codec": codec,
                "receiver": receiver,
                "camera": key.split(":", 1)[1],
                "requested_seconds": data["requested_seconds"],
                "requested_frames": data.get("requested_frames", ""),
                "requested_fps": data["configuration"]["fps"],
                "duration_s": data["duration_seconds"],
                "observed_seconds": report["observation_seconds"],
                "received_frames": report["frames"],
                "sampled_frames": path["sampled"],
                "complete_frames": path["count"],
                "clock_error_ms": path["error_ms"],
                "receive_fps": report["fps"],
                "viewer_fps": stream.get("submitted_fps", stream.get("fps")),
                "sequence_gaps": report["sequence_gaps"],
                "source_frames": source_report["frames"],
                "source_fps": source_report["fps"],
                "result": filename.name,
                "transport_clock_error_ms": report.get("delivery_clock_error_ms", ""),
            }
            for label, values in {
                "total_ms": path["total"],
                "source_total_ms": source_report["path"]["total"],
                "decode_ms": path.get("decode", metrics.get("decode_ms", {})),
                "upload_ms": metrics.get("unpack_ms", {}),
                "transport_ms": metrics.get("delivery_ms", {}),
                "frame_spacing_ms": metrics.get("receive_interval_ms", {}),
                **{
                    name: metrics.get(name, {})
                    for name in ("encode_ms", "pack_ms", "payload_bytes", "transport_frame_bytes")
                },
            }.items():
                for percentile in PERCENTILES:
                    row[f"{label}_{percentile}"] = values.get(percentile, "")
            for name in ("payload_bytes", "transport_frame_bytes"):
                row[f"{name}_mean"] = metrics.get(name, {}).get("mean", "")
            if receiver == "webrtc":
                before = data["browser_before"][key]
                after = data["browser_after"][key]
                row["viewer_fps"] = (
                    after["frames"]["total"]
                    - before["frames"]["total"]
                    - after["frames"]["dropped"]
                    + before["frames"]["dropped"]
                ) / data["duration_seconds"]
                row["browser_dropped"] = after["frames"]["dropped"] - before["frames"]["dropped"]
                first, last = before["inbound"][0], after["inbound"][0]
                for name in ("packetsLost", "freezeCount", "framesDecoded", "framesDropped"):
                    row[f"browser_{name}"] = last.get(name, 0) - first.get(name, 0)
                row["browser_decoder"] = last.get("decoderImplementation", "not reported")
                row["browser_power_efficient_decoder"] = last.get(
                    "powerEfficientDecoder", "not reported"
                )
            rows.append(row)
            for name, values in path["stages"].items():
                stages.append(
                    {
                        **{
                            key: row[key]
                            for key in (
                                "sdk",
                                "source",
                                "camera",
                                "width",
                                "height",
                                "codec",
                                "receiver",
                                "complete_frames",
                            )
                        },
                        "stage": name,
                        **values,
                    }
                )
    if len(rows) != 74 or len(set(row["result"] for row in rows)) != 48:
        raise ValueError("Expected 48 SDK 5 configurations / 74 camera results")
    return rows, stages, sorted(set(dates))


def format_size(value):
    value = float(value)
    return f"{value / 1048576:.2f} MiB" if value >= 1048576 else f"{value / 1024:.1f} KiB"


def table(rows, percentile=None, baseline=None):
    headings = ["RES", "CC", "FPS"] + (
        ["P50", "P95", "P99", "P99.9"]
        if baseline
        else ["FS", "Encode (ms)", "Transport (ms)", "Decode (ms)", "Total (ms)"]
    )
    output = [
        "<table>",
        "    <thead>",
        "        <tr>"
        + "".join(
            f'<th align="{"left" if i < 2 else "right"}">{name}</th>'
            for i, name in enumerate(headings)
        )
        + "</tr>",
        "    </thead>",
        "    <tbody>",
    ]
    for width, resolution in (("1920", "FHD"), ("2560", "QHD"), ("3840", "4K")):
        group = sorted(
            (r for r in rows if r["width"] == width), key=lambda r: list(CODECS).index(r["codec"])
        )
        for index, row in enumerate(group):
            cells = []
            if index == 0:
                span = f' rowspan="{len(group)}"' if len(group) > 1 else ""
                cells.append(f"<td{span}>{resolution}</td>")
            values = [CODECS[row["codec"]]]
            if baseline:
                old = baseline[row["codec"], width]
                for field in ["viewer_fps", *[f"total_ms_{p}" for p in PERCENTILES]]:
                    values.append(f"{float(old[field]):.2f} → {float(row[field]):.2f}")
            else:
                encode = "pack_ms" if row["codec"] == "raw-bgr8" else "encode_ms"
                decode = "upload_ms" if row["codec"] == "raw-bgr8" else "decode_ms"
                values += [
                    f"{float(row['viewer_fps']):.2f}",
                    format_size(row["transport_frame_bytes_mean"]),
                ]
                values += [
                    f"{float(row[f'{name}_{percentile}']):.2f}"
                    for name in (encode, "transport_ms", decode, "total_ms")
                ]
            for i, value in enumerate(values):
                if row["codec"] in {"h264", "h265"}:
                    value = f"<strong>{value}</strong>"
                align = ' align="right"' if i else ""
                cells.append(f"<td{align}>{value}</td>")
            output.append("        <tr>" + "".join(cells) + "</tr>")
    return "\n".join([*output, "    </tbody>", "</table>"])


def documents(rows, dates):
    current = [row for row in rows if row["sdk"] == "5"]
    date_label = " / ".join(dates)
    collected = (
        f"SDK 5 measurements collected {date_label} on public EA3. "
        "The SDK 4 baseline is retained from October 2, 2026."
    )
    caveat = (
        "HSB capture runs SDK 4.6.0; its coordinator and surgeon run SDK 5. "
        "All other refreshed sources run SDK 5."
    )
    for path, compare in (
        (ROOT.parent / "BENCHMARK.md", False),
        (ROOT.parent / "docs/BENCHMARK_COMPARISON.md", True),
    ):
        content = path.read_text().replace("\n\n" + caveat, "")
        content = re.sub(
            r"SDK 5 measurements collected [^\n]+", collected + "\n\n" + caveat, content, count=1
        )
        generated = []
        for receiver in ("holoviz",) if compare else ("holoviz", "webrtc"):
            for source, camera, _ in SOURCES:
                selected = [
                    r
                    for r in current
                    if (r["source"], r["camera"], r["receiver"]) == (source, camera, receiver)
                ]
                old = {
                    (r["codec"], r["width"]): r
                    for r in rows
                    if (r["sdk"], r["source"], r["camera"], r["receiver"])
                    == ("4", source, camera, receiver)
                }
                generated.extend(
                    [table(selected, baseline=old)]
                    if compare
                    else [table(selected, p) for p in PERCENTILES]
                )
        if len(re.findall(r"<table>.*?</table>", content, re.S)) != len(generated):
            raise ValueError(f"Unexpected table layout in {path}")
        tables = iter(generated)
        content = re.sub(
            r"<table>.*?</table>", lambda _, tables=tables: next(tables), content, flags=re.S
        )
        if compare:

            def changes(source, camera, field, receiver="holoviz"):
                paired = []
                for row in current:
                    if row["receiver"] != receiver or (
                        source and (row["source"], row["camera"]) != (source, camera)
                    ):
                        continue
                    old = next(
                        r
                        for r in rows
                        if r["sdk"] == "4"
                        and all(
                            r[k] == row[k]
                            for k in ("source", "camera", "width", "codec", "receiver")
                        )
                    )
                    key = (
                        ("pack_ms_p99" if field == "encode_ms_p99" else "upload_ms_p99")
                        if row["codec"] == "raw-bgr8"
                        and field in {"encode_ms_p99", "decode_ms_p99"}
                        else field
                    )
                    paired.append((float(row[key]) / float(old[key]) - 1) * 100)
                return paired

            deltas = changes(None, None, "total_ms_p99")
            content = re.sub(
                r"SDK 5 EA3 has lower P99 total latency[^\n]+",
                f"SDK 5 EA3 has lower P99 total latency in **{sum(v < 0 for v in deltas)} "
                f"of {len(deltas)}** matched Holoviz results. The median per-result change is "
                f"**{median(deltas):+.1f}%**. These runs also include application and "
                "capture-backend changes since the SDK 4 baseline; differences cannot be "
                "attributed to the SDK alone.",
                content,
            )
            summaries = [
                ([f"total_ms_{p}" for p in PERCENTILES], "holoviz"),
                (["encode_ms_p99", "transport_ms_p99", "decode_ms_p99", "viewer_fps"], "holoviz"),
                ([f"total_ms_{p}" for p in PERCENTILES], "webrtc"),
            ]
            for index, (fields, receiver) in enumerate(summaries):
                for source, camera, label in SOURCES:
                    replacement = (
                        "| "
                        + label
                        + " | "
                        + " | ".join(
                            f"{median(changes(source, camera, field, receiver)):+.1f}%"
                            for field in fields
                        )
                        + " |"
                    )
                    pattern = rf"^\| {re.escape(label)}\s+\|[^\n]+"
                    target = list(re.finditer(pattern, content, re.M))[index]
                    content = content[: target.start()] + replacement + content[target.end() :]
            fps = [float(r["source_fps"]) for r in current if r["source"] == "brio-host"]
            content = re.sub(
                r"- Refreshed BRIO runs[^\n]+",
                (
                    f"- Refreshed BRIO runs requested 30 FPS; recorded source rates span "
                    f"{min(fps):.1f}–{max(fps):.1f} FPS. Exposure and dynamic framerate settings "
                    "can reduce capture rate in low light. Source-rate differences confound FPS "
                    "and latency comparisons with SDK 4; they do not establish an SDK regression."
                ),
                content,
            )
        else:
            content = content.replace(
                "Source and receiver both use Holoscan `5.0.0a3 (public EA3)`.",
                "The coordinator and receiver use Holoscan `5.0.0a3 (public EA3)`; "
                "HSB capture uses `4.6.0` and all other sources use SDK 5.",
            )
        content = re.sub(
            r"^\|[^\n]+\|$",
            lambda match: (
                "| " + " | ".join(cell.strip() for cell in match[0][1:-1].split("|")) + " |"
            ),
            content,
            flags=re.M,
        )
        path.write_text(content)


def main():
    fields, old_rows = read_csv("summary.csv")
    stage_fields, old_stages = read_csv("stages.csv")
    rows, stages, dates = records()
    rows += [row for row in old_rows if row["sdk"] == "4"]
    stages += [row for row in old_stages if row["sdk"] == "4"]
    documents(rows, dates)
    write_csv("summary.csv", fields, rows)
    write_csv("stages.csv", stage_fields, stages)


if __name__ == "__main__":
    main()
