# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Independent Holoscan viewer: patient TLS endpoint -> GPU frames -> Holoviz."""

import argparse
import asyncio
import json
import os
import signal
import time
from pathlib import Path

from telesurgery_core.diagnostics.benchmark import Benchmark
from telesurgery_core.diagnostics.clock import Clock
from telesurgery_core.diagnostics.trace import arrive, mark
from telesurgery_core.transport.peer import Peer
from telesurgery_core.transport.protocol import decode_video
from telesurgery_core.transport.tls import client_context, pin_peer
from telesurgery_core.video.codecs import CodecWorker
from telesurgery_core.video.config import Config
from telesurgery_core.video.depth import render
from telesurgery_core.video.view import crop
from telesurgery_core.video.view import settings as zoom_settings
from telesurgery_runtime.application.pipeline import Frames
from telesurgery_runtime.backends.sdk import backend


class ReceiveDecode:
    def __init__(self, depth_enabled=False):
        self.pending, self.benchmark = Frames(), Benchmark()
        self.frames = 0
        self.received_at = time.monotonic()
        self.trace = None
        self.depth_enabled = depth_enabled
        self.display = {"mode": "color", "distance": 2.0, "opacity": 0.4}
        self.zoom = zoom_settings()

    def put(self, header, data, timing=None):
        header, data = decode_video([json.dumps(header).encode(), data])
        self.received_at = time.monotonic()
        self.benchmark.observe(header)
        self.benchmark.encoded(header, data)
        if timing:
            self.benchmark.delivery(timing)
        received = timing["received_ns"] if timing else time.monotonic_ns()
        self.pending.put("video", (header, data, received, timing.get("trace") if timing else None))

    def start(self):
        self.decoder, self.codec = None, None
        self.decoder_key = None

    def compute(self):
        packet = self.pending.compute()
        if packet is None:
            return None
        stamp = time.perf_counter()
        header, data, received, trace = packet
        trace = mark(trace, "receiver_queue_ms")
        self.benchmark.add("receiver_queue_ms", (time.monotonic_ns() - received) / 1e6)
        key = header.codec, header.codec_profile, header.width, header.height
        if getattr(self, "decoder_key", None) != key:
            if self.decoder:
                self.decoder.close()
            self.decoder = None
            self.decoder = CodecWorker(
                Config(codec=header.codec, width=header.width, height=header.height), encode=False
            )
            self.codec = header.codec
            self.decoder_key = key
        frame = self.decoder.decode_device(header, data)
        stage = "unpack_ms" if header.codec == "raw-bgr8" else "decode_ms"
        self.trace = mark(trace, stage)
        self.decoded_ns = time.monotonic_ns()
        self.benchmark.add(stage, (time.perf_counter() - stamp) * 1000)
        self.frames += 1
        image = crop(render(frame.image, frame.depth, **self.display), **self.zoom)
        # Depth composition already waits for its GPU work. Zoom itself only
        # changes tensor metadata; sampling/scaling is part of Holoviz rendering.
        self.prepared_ns = time.monotonic_ns()
        self.trace = mark(self.trace, "view_processing_ms", self.prepared_ns)
        self.benchmark.add("view_processing_ms", (self.prepared_ns - self.decoded_ns) / 1e6)
        return image

    def submitted(self):
        trace = mark(self.trace, "render_submit_ms")
        self.benchmark.add("render_submit_ms", (time.monotonic_ns() - self.prepared_ns) / 1e6)
        if trace:
            self.benchmark.finish(trace, "holoviz")

    def stop(self):
        if self.decoder:
            self.decoder.close()


async def run(config, report):
    stopped = asyncio.Event()
    source = ReceiveDecode(config.get("depth", False))
    source.zoom = zoom_settings(**config.get("zoom", {}))
    source.display.update(config.get("display", {}))
    clock = Clock()
    clock_task = asyncio.create_task(clock.watch())
    session = None
    parent = os.getppid()

    async def event(peer, name, params, payload):
        if name == "video" and params["camera"] == config["camera"]:
            timing = peer.delivery(params.get("timing"), frame_bytes=params.get("transport_bytes"))
            timing["trace"] = arrive(params.get("trace"), timing)
            source.put(params["header"], payload, timing)

    async def reject(peer, method, params):
        raise PermissionError("Native viewer accepts video only")

    reader, writer = await asyncio.open_connection(
        config["host"], config["port"], ssl=client_context()
    )
    try:
        pin_peer(writer, f"{config['host']}:{config['port']}", report.parent, config["fingerprint"])
        peer = Peer(reader, writer, reject, event, clock=clock).start()
        try:
            await peer.call("viewer.attach", {"ticket": config["ticket"]})
            candidate = backend("viewer").build(
                source, config["width"], config["height"], config["name"]
            )
            await asyncio.to_thread(candidate.__enter__)
            session = candidate
            loop = asyncio.get_running_loop()
            for number in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(number, stopped.set)
            metrics, next_metrics, next_report = {}, 0, 0
            reset_request = report.with_name("reset-metrics")
            display_request = report.with_name("display.json")
            zoom_request = report.with_name("zoom.json")
            request_versions = {}
            while not stopped.is_set() and not peer.closed.is_set() and os.getppid() == parent:
                if not session.is_running():
                    break
                if time.monotonic() - source.received_at > 5:
                    raise RuntimeError("Camera stopped delivering frames")
                if source.frames:
                    for path, attribute in ((display_request, "display"), (zoom_request, "zoom")):
                        if path.exists() and path.stat().st_mtime_ns != request_versions.get(path):
                            request_versions[path] = path.stat().st_mtime_ns
                            values = json.loads(path.read_text())
                            setattr(
                                source,
                                attribute,
                                zoom_settings(**values) if attribute == "zoom" else values,
                            )
                    resetting = reset_request.exists()
                    if resetting:
                        source.benchmark.reset()
                        next_metrics = 0
                    if time.monotonic() >= next_metrics:
                        metrics = await asyncio.to_thread(source.benchmark.report)
                        next_metrics = time.monotonic() + 5
                    if resetting or time.monotonic() >= next_report:
                        write_status(
                            report,
                            {
                                "status": "running",
                                "frames": source.frames,
                                "codec": source.codec,
                                "display": source.display,
                                "zoom": source.zoom,
                                "metrics": metrics,
                            },
                        )
                        next_report = time.monotonic() + 0.5
                    if resetting:
                        reset_request.unlink(missing_ok=True)
                try:
                    await asyncio.wait_for(stopped.wait(), 0.05)
                except TimeoutError:
                    pass
        finally:
            if session is not None:
                await asyncio.to_thread(session.__exit__, None, None, None)
            await peer.close()
    finally:
        clock_task.cancel()
        await asyncio.gather(clock_task, return_exceptions=True)
        writer.close()
    write_status(report, {"status": "closed", "frames": source.frames})


def write_status(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, allow_nan=False))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    report = args.config.with_name("status.json")
    try:
        asyncio.run(run(json.loads(args.config.read_text()), report))
    except Exception as exc:
        write_status(report, {"status": "error", "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
