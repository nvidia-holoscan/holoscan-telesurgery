# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Local-only browser interface. Remote peers use the separate application endpoint."""

import asyncio
import signal
from pathlib import Path

from aiohttp import web
from telesurgery.server.application import Application
from telesurgery_core.diagnostics.logs import read_log


@web.middleware
async def local_requests(request, handler):
    if request.host.split(":")[0] not in {"localhost", "127.0.0.1"}:
        raise web.HTTPForbidden(text="Use the local dashboard address")
    origin = request.headers.get("Origin")
    if origin and origin != f"http://{request.host}":
        raise web.HTTPForbidden(text="Cross-origin dashboard access is disabled")
    if request.method == "POST" and request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="Expected application/json")
    try:
        return await handler(request)
    except (ValueError, KeyError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except PermissionError as exc:
        return web.json_response({"error": str(exc)}, status=403)
    except (RuntimeError, ConnectionError, OSError, TimeoutError) as exc:
        return web.json_response({"error": str(exc)}, status=409)


def create_app(service):
    app = web.Application(middlewares=[local_requests], client_max_size=128 * 1024)
    static = Path(__file__).with_name("static")

    async def index(request):
        return web.FileResponse(static / "index.html", headers={"Cache-Control": "no-store"})

    async def status(request):
        return web.json_response(
            await service.status(
                metrics=request.query.get("metrics") == "1", device=request.query.get("device")
            ),
            headers={"Cache-Control": "no-store"},
        )

    async def simulation_log(request):
        if service.simulation is None:
            return web.json_response({"error": "No simulation is running"}, status=404)
        return web.json_response(
            await asyncio.to_thread(service.simulation.log), headers={"Cache-Control": "no-store"}
        )

    async def node_log(request):
        node = request.match_info["node"]
        if service.role != "patient" or node not in service.node_registry.configs:
            raise web.HTTPNotFound()
        if request.query.get("source") == "simulation":
            return web.json_response(
                await service.node_call(node, "simulation.log"),
                headers={"Cache-Control": "no-store"},
            )
        prefix = (
            "connect" if service.node_registry.configs[node].get("kind") == "service" else "deploy"
        )
        path = service.directory / f"{prefix}-{node}.log"

        return web.json_response(
            await asyncio.to_thread(read_log, path), headers={"Cache-Control": "no-store"}
        )

    async def action(request):
        body = await request.json()
        return web.json_response(
            {"result": await service.action(body["action"], body.get("params", {}))}
        )

    async def offer(request):
        body = await request.json()
        if service.native.status().get(body["camera"], {}).get("status") in {"starting", "running"}:
            raise ValueError("Choose Show in browser to switch back from Holoviz")
        if service.role == "surgeon":
            if service.remote_status.get("status") != "approved":
                raise PermissionError("Patient approval is required")
            if body["camera"] not in service.selected:
                raise PermissionError("Select the camera before opening its video")
        else:
            if body["camera"] not in {c["id"] for c in service.inventory()["cameras"]}:
                raise ValueError("Unknown camera")
        return web.json_response(
            await service.media.offer(body["camera"], body["sdp"], body["type"])
        )

    async def lifecycle(app):
        # SDK 4 installs native signal handlers while starting GXF. Restore the
        # web runner handlers so device graphs remain alive during orderly cleanup.
        def shutdown():
            raise web.GracefulExit

        loop = asyncio.get_running_loop()
        try:
            await service.start()
            for number in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(number, shutdown)
            yield
        finally:
            await service.close()

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/simulation/log", simulation_log)
    app.router.add_get("/api/nodes/{node}/log", node_log)
    app.router.add_post("/api/action", action)
    app.router.add_post("/api/offer", offer)
    app.router.add_static("/static", static)
    return app


def serve(
    role,
    port,
    endpoint_port,
    directory,
    environment=None,
    *,
    sim_gui=False,
    nodes=(),
):
    import fcntl

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "service.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another service is using this state directory") from exc
        service = Application(
            role, directory, endpoint_port, environment, sim_gui=sim_gui, nodes=nodes
        )
        web.run_app(
            create_app(service),
            host="127.0.0.1",
            port=port,
            access_log=None,
            shutdown_timeout=5,
        )
