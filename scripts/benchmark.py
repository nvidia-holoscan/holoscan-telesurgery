#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Collect the dashboard's measurements from real camera streams and viewers."""

import argparse
import asyncio
import math
import time
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path

import aiohttp
from telesurgery_core.diagnostics.benchmark import write_report


class Dashboard:
    def __init__(self, http, address):
        self.http, self.address = http, address.rstrip("/")

    async def request(self, path, body=None):
        async with self.http.request(
            "GET" if body is None else "POST", self.address + path, json=body
        ) as response:
            data = await response.json()
            if response.status != 200:
                raise RuntimeError(data.get("error", str(data)))
            return data

    async def status(self, metrics=False):
        return await self.request("/api/status" + ("?metrics=1" if metrics else ""))

    async def action(self, method, **params):
        return (await self.request("/api/action", {"action": method, "params": params}))["result"]


async def browser_snapshot(page):
    return await page.evaluate("""async () => Object.fromEntries(
        await Promise.all([...benchmarkTiles].map(async ([id,tile])=>[id,{
            frames:(()=>{const q=tile.tile.querySelector('video').getVideoPlaybackQuality();
                return {total:q.totalVideoFrames,dropped:q.droppedVideoFrames}})(),
            inbound:[...(await tile.peer.getStats()).values()].filter(
                s=>s.type==='inbound-rtp' && s.kind==='video'),
        }])) )""")


async def browser_open(playwright, address, cameras):
    browser = await playwright.chromium.launch(
        headless=False, args=["--autoplay-policy=no-user-gesture-required"]
    )
    page = await browser.new_page(viewport={"width": 1600, "height": 1000})

    async def expose_tiles(route):
        response = await route.fetch()
        # Expose the existing UI peers; do not create extra streams or alter playback.
        await route.fulfill(
            response=response,
            body=await response.text() + "\nglobalThis.benchmarkTiles=tiles;\n",
        )

    await page.route("**/static/app.js", expose_tiles)
    try:
        await page.goto(address)
        await page.wait_for_function(
            "ids=>ids.every(id=>benchmarkTiles.get(id)?.tile.querySelector('video').videoWidth>0)",
            arg=cameras,
            timeout=60000,
        )
        await page.evaluate("""async () => {
            const {latencyReader}=await import('/static/latency.js');
            window.benchmarkRead=latencyReader(benchmarkTiles);
            window.benchmarkSignal=new AbortController().signal;
        }""")
        return browser, page
    except BaseException:
        await browser.close()
        raise


async def run(args):
    report = {
        "started_utc": datetime.now(UTC).isoformat(),
        "receiver": args.receiver,
        "requested_seconds": args.seconds,
        "warmup_seconds": args.warmup,
        "configuration": {
            "width": args.width,
            "height": args.height,
            "codec": args.codec,
            "fps": args.fps,
            "pixel_format": args.pixel_format,
            "qp": 24,
            "encoder_preset": "P1",
            "jpeg_quality": 85,
        },
        "sampling": "Timed collection after warmup; actual valid counts are recorded",
        "boundary": "Application buffer availability to Holoviz submission"
        if args.receiver == "holoviz"
        else "Application buffer availability to estimated browser display",
    }
    async with (
        aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as http,
        AsyncExitStack() as viewers,
    ):
        patient, surgeon = Dashboard(http, args.patient), Dashboard(http, args.surgeon)
        initial = await patient.status()
        cameras = {c["id"]: c for c in initial["cameras"]}
        if any(key not in cameras for key in args.camera):
            raise ValueError("Selected cameras have not been discovered")
        report["source_sdk"] = initial["sdk"]
        report["receiver_sdk"] = (await surgeon.status())["sdk"]
        report["nodes"] = [
            n for n in initial["nodes"] if any(key.startswith(n["id"] + ":") for key in args.camera)
        ]
        page = None
        try:
            await surgeon.action("disconnect")
            grant = await surgeon.action(
                "connect", address=args.endpoint, name="Benchmark", robot=False
            )
            if grant["status"] == "pending":
                await patient.action("access.approve", id=grant["id"], robot=False)
            await surgeon.action("view", cameras=[])
            for key in args.camera:
                await patient.action("camera.stop", id=key)
                await patient.action("camera.start", id=key, settings=report["configuration"])
            async with asyncio.timeout(120):
                while True:
                    state = await patient.status()
                    selected = [c for c in state["cameras"] if c["id"] in args.camera]
                    errors = [c["error"] for c in selected if c["status"] == "error"]
                    if errors:
                        raise RuntimeError(str(errors))
                    if len(selected) == len(args.camera) and all(
                        c["status"] == "live" for c in selected
                    ):
                        break
                    await asyncio.sleep(1)
            report["cameras"] = selected
            # The surgeon receives inventory independently of the patient's HTTP reply.
            async with asyncio.timeout(30):
                while True:
                    inventory = (await surgeon.status())["session"].get("cameras", [])
                    live = {c["id"] for c in inventory if c["status"] == "live"}
                    if set(args.camera) <= live:
                        break
                    await asyncio.sleep(0.2)
            await surgeon.action("view", cameras=args.camera)
            if args.receiver == "holoviz":
                for key in args.camera:
                    await surgeon.action("view.holoviz", camera=key)
            else:
                from playwright.async_api import async_playwright

                playwright = await viewers.enter_async_context(async_playwright())
                browser, page = await browser_open(playwright, args.surgeon, args.camera)
                viewers.push_async_callback(browser.close)

            async def read():
                if page:
                    value = await page.evaluate(
                        "async () => JSON.parse(JSON.stringify("
                        "await benchmarkRead(benchmarkSignal)))"
                    )
                    return {s["id"]: s for s in value["streams"]}
                state = await surgeon.status(metrics=True)
                result = {}
                for key in args.camera:
                    native = state["native_views"].get(key, {})
                    if native.get("status") != "running":
                        raise RuntimeError(f"Viewer {key}: {native}")
                    metrics = native.get("metrics", {})
                    result[key] = {
                        "report": metrics,
                        "path": metrics.get("path", {}),
                        "submitted_frames": native["frames"],
                    }
                return result

            deadline = time.monotonic() + args.warmup
            while time.monotonic() < deadline:
                await read()
                await asyncio.sleep(2)
            await patient.action("metrics.reset")
            await surgeon.action("metrics.reset")
            if page:
                await page.evaluate("[...benchmarkTiles.values()].forEach(t=>t.timing.reset())")
                report["browser_before"] = await browser_snapshot(page)
            baseline = await read()
            started = time.monotonic()
            next_progress = 0
            while True:
                streams = await read()
                counts = {key: value["path"].get("sampled", 0) for key, value in streams.items()}
                elapsed = time.monotonic() - started
                if elapsed >= next_progress:
                    print(f"{elapsed:.0f}s: {counts}", flush=True)
                    next_progress += 30
                    write_report(
                        args.output.with_suffix(".progress.json"),
                        {
                            "configuration": report["configuration"],
                            "elapsed_seconds": elapsed,
                            "samples": counts,
                        },
                    )
                if elapsed >= args.seconds:
                    break
                await asyncio.sleep(min(5, args.seconds - elapsed))
            if len(counts) != len(args.camera) or not counts or min(counts.values()) == 0:
                raise RuntimeError("No frame timing samples were collected for a selected camera")
            report["duration_seconds"] = time.monotonic() - started
            report["streams"] = streams
            source = (await patient.status(metrics=True))["video"]
            report["source_metrics"] = {key: source.get(key, {}) for key in args.camera}
            for key, value in streams.items():
                if not page:
                    value["submitted_fps"] = (
                        value["submitted_frames"] - baseline[key]["submitted_frames"]
                    ) / report["duration_seconds"]
            if page:
                report["browser_after"] = await browser_snapshot(page)
                await page.screenshot(path=str(args.output.with_suffix(".png")))
            report["status"] = "measured"
        except BaseException as exc:
            report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            report["finished_utc"] = datetime.now(UTC).isoformat()
            for key in args.camera:
                try:
                    await surgeon.action("view.close", camera=key)
                    await patient.action("camera.stop", id=key)
                except (RuntimeError, aiohttp.ClientError, TimeoutError):
                    pass

            write_report(args.output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patient", default="http://127.0.0.1:8000")
    parser.add_argument("--surgeon", default="http://127.0.0.1:8002")
    parser.add_argument("--endpoint", default="127.0.0.1:7447")
    parser.add_argument("--camera", action="append", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--pixel-format", default="")
    parser.add_argument("--codec", choices=["h264", "h265", "nvjpeg", "raw-bgr8"], default="h264")
    parser.add_argument("--receiver", choices=["holoviz", "webrtc"], default="holoviz")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--warmup", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 5:
        parser.error("--seconds must be finite and at least 5")
    if not math.isfinite(args.warmup) or args.warmup < 0:
        parser.error("--warmup must be finite and nonnegative")
    if args.receiver == "webrtc" and args.codec != "h264":
        parser.error("The browser receives H.264; use Holoviz for other codecs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
