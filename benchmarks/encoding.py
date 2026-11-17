# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compare the former encoder defaults with the bitrate-limited defaults.

The baseline is every H.264/H.265 configuration of the SDK 5 matrix, measured with
constant QP 24 and independent frames on the same day and scenes as the refreshed
records in ``results/matrix``.

``python benchmarks/encoding.py --baseline DIR`` rebuilds ``results/encoding_baseline.csv``
from baseline records; ``python benchmarks/encoding.py`` rewrites the generated tables
in ``docs/BENCHMARK_ENCODING.md``.
"""

import argparse
import csv
import json
import re
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
DOCUMENT = ROOT.parent / "docs/BENCHMARK_ENCODING.md"
BASELINE = ROOT / "results/encoding_baseline.csv"
SOURCES = (
    ("mira-host", "procedure", "x86 · MIRA Procedure Camera"),
    ("mira-host", "room", "x86 · MIRA Room Camera"),
    ("brio-host", "usb-1e29b43c150f", "x86 · Logitech BRIO Camera"),
    ("imx274-thor", "hsb-192.168.0.2-0", "Thor · IMX274 Camera"),
    ("mira-spark", "procedure", "DGX Spark · MIRA Procedure Camera"),
    ("mira-spark", "room", "DGX Spark · MIRA Room Camera"),
)
RESOLUTIONS = {"1920": "FHD", "2560": "QHD", "3840": "4K"}
CODECS = {"h264": "H.264", "h265": "H.265"}
FIELDS = (
    "source",
    "camera",
    "width",
    "height",
    "codec",
    "receiver",
    "finished_utc",
    "receive_fps",
    "viewer_fps",
    "sequence_gaps",
    "payload_bytes_mean",
    "payload_bytes_max",
    "total_ms_p50",
    "total_ms_p95",
    "total_ms_p99",
    "total_ms_p99_9",
)


def record_rows(directory):
    """One row per camera result, with the columns both sides of the comparison share."""
    rows = []
    for filename in sorted(Path(directory).glob("sdk5-*.json")):
        match = re.fullmatch(r"sdk5-(.+)-(\d+)x(\d+)-(h26[45])-(holoviz|webrtc)", filename.stem)
        if not match:
            continue
        source, width, height, codec, receiver = match.groups()
        data = json.loads(filename.read_text())
        if data["status"] != "measured":
            raise ValueError(f"Unmeasured record: {filename}")
        for key, stream in data["streams"].items():
            report, path = stream["report"], stream["path"]
            viewer_fps = stream.get("submitted_fps", stream.get("fps"))
            if receiver == "webrtc":
                before = data["browser_before"][key]["frames"]
                after = data["browser_after"][key]["frames"]
                viewer_fps = (
                    after["total"] - before["total"] - after["dropped"] + before["dropped"]
                ) / data["duration_seconds"]
            size = report["steady_metrics"]["payload_bytes"]
            rows.append(
                {
                    "source": source,
                    "camera": key.split(":", 1)[1],
                    "width": width,
                    "height": height,
                    "codec": codec,
                    "receiver": receiver,
                    "finished_utc": data["finished_utc"],
                    "receive_fps": report["fps"],
                    "viewer_fps": viewer_fps,
                    "sequence_gaps": report["sequence_gaps"],
                    "payload_bytes_mean": size["mean"],
                    "payload_bytes_max": size["max"],
                    **{f"total_ms_{p}": path["total"][p] for p in ("p50", "p95", "p99", "p99_9")},
                }
            )
    return rows


def read(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def key(row):
    return tuple(row[name] for name in ("source", "camera", "width", "codec", "receiver"))


def mbps(row):
    return float(row["payload_bytes_mean"]) * 8 * float(row["receive_fps"]) / 1e6


def change(before, after):
    return (after / before - 1) * 100


def tables(baseline, current):
    """Markdown per camera: before -> after for each resolution, codec and viewer."""
    output = []
    for source, camera, label in SOURCES:
        output += [
            f"### {label}",
            "",
            "| RES | CC | Viewer | FPS | Mbit/s | Largest frame (KiB) | P50 (ms) | P99 (ms) |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for width, resolution in RESOLUTIONS.items():
            for codec, codec_label in CODECS.items():
                for receiver, viewer in (("holoviz", "Holoviz"), ("webrtc", "Browser")):
                    old = baseline.get((source, camera, width, codec, receiver))
                    new = current.get((source, camera, width, codec, receiver))
                    if not old or not new:
                        continue
                    cells = [
                        f"{float(old['viewer_fps']):.1f} → {float(new['viewer_fps']):.1f}",
                        f"{mbps(old):.1f} → **{mbps(new):.1f}**",
                        f"{float(old['payload_bytes_max']) / 1024:.0f} → "
                        f"{float(new['payload_bytes_max']) / 1024:.0f}",
                        f"{float(old['total_ms_p50']):.2f} → **{float(new['total_ms_p50']):.2f}**",
                        f"{float(old['total_ms_p99']):.2f} → **{float(new['total_ms_p99']):.2f}**",
                    ]
                    output.append(
                        f"| {resolution} | {codec_label} | {viewer} | " + " | ".join(cells) + " |"
                    )
        output.append("")
    return "\n".join(output).rstrip()


def summary(baseline, current):
    lines = []
    for receiver, viewer in (("holoviz", "Holoviz"), ("webrtc", "Browser")):
        pairs = [
            (baseline[k], row) for k, row in current.items() if k[4] == receiver and k in baseline
        ]
        rates = [change(mbps(old), mbps(new)) for old, new in pairs]
        delays = {
            name: [change(float(old[name]), float(new[name])) for old, new in pairs]
            for name in ("total_ms_p50", "total_ms_p99")
        }
        gaps = sum(int(new["sequence_gaps"]) for _, new in pairs)
        lines.append(
            f"| {viewer} | {len(pairs)} | {median(rates):+.0f}% "
            f"({min(rates):+.0f}% to {max(rates):+.0f}%) | "
            f"{median(delays['total_ms_p50']):+.1f}% | {median(delays['total_ms_p99']):+.1f}% | "
            f"{sum(v < 0 for v in delays['total_ms_p99'])} of {len(pairs)} | {gaps} |"
        )
    return "\n".join(
        [
            "| Viewer | Results | Bitrate, median (range) | Total P50, median | "
            "Total P99, median | Lower P99 | Sequence gaps after |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            *lines,
        ]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, help="directory of QP 24 all-IDR records")
    args = parser.parse_args()
    current = {key(row): row for row in record_rows(ROOT / "results/matrix")}
    if args.baseline:
        # Check the candidate records before the stored baseline is replaced.
        candidate = record_rows(args.baseline)
        if {key(row) for row in candidate} != current.keys():
            raise ValueError(f"Baseline records in {args.baseline} do not match results/matrix")
        with BASELINE.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(candidate)
    baseline = {key(row): row for row in read(BASELINE)}
    if baseline.keys() != current.keys():
        raise ValueError(f"Unmatched results: {sorted(baseline.keys() ^ current.keys())}")
    content = DOCUMENT.read_text()
    for name, generated in (
        ("summary", summary(baseline, current)),
        ("tables", tables(baseline, current)),
    ):
        pattern = rf"(<!-- {name}:begin -->\n)(?:.*?\n)?(<!-- {name}:end -->)"
        if not re.search(pattern, content, re.S):
            raise ValueError(f"Missing {name} markers in {DOCUMENT}")
        content = re.sub(
            pattern, lambda m, text=generated: f"{m[1]}{text}\n{m[2]}", content, flags=re.S
        )
    DOCUMENT.write_text(content)


if __name__ == "__main__":
    main()
