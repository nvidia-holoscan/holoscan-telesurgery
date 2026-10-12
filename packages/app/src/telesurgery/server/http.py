# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Browser interface. Nodes and surgeons use the separate application endpoint."""

import asyncio
import logging
import signal
from pathlib import Path

from aiohttp import web
from telesurgery.server.application import Application
from telesurgery.server.security import (
    dashboard_client_host,
    dashboard_requests,
    dashboard_tls,
    security_headers,
)


def create_app(service, host="127.0.0.1"):
    app = web.Application(middlewares=[dashboard_requests(host)], client_max_size=128 * 1024)
    app.on_response_prepare.append(security_headers)
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

    async def node_log(request):
        node = request.match_info["node"]
        if service.role != "patient" or node not in service.node_registry.configs:
            raise web.HTTPNotFound()
        if request.query.get("source") == "simulation":
            return web.json_response(
                await service.node_call(node, "simulation.log"),
                headers={"Cache-Control": "no-store"},
            )
        return web.json_response(
            await service.node_call(node, "node.log"), headers={"Cache-Control": "no-store"}
        )

    async def action(request):
        body = await request.json()
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("action"), str)
            or not isinstance(body.get("params", {}), dict)
        ):
            raise ValueError("Expected an action name and parameters object")
        try:
            result = await service.action(body["action"], body.get("params", {}))
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Action %s (%s) failed: %s",
                body.get("action"),
                body.get("params", {}).get("id", ""),
                exc,
            )
            raise
        return web.json_response({"result": result})

    async def camera_log(request):
        camera = request.match_info["camera"]
        if service.role != "patient" or camera not in {
            item["id"] for item in service.inventory()["cameras"]
        }:
            raise web.HTTPNotFound()
        node, key = camera.split(":", 1)
        return web.json_response(
            await service.node_call(node, "camera.log", {"id": key}),
            headers={"Cache-Control": "no-store"},
        )

    async def robot_log(request):
        robot = request.match_info["robot"]
        if service.role != "patient" or robot not in {
            item["id"] for item in service.inventory()["robots"]
        }:
            raise web.HTTPNotFound()
        node, key = robot.split(":", 1)
        return web.json_response(
            await service.node_call(node, "robot.log", {"id": key}),
            headers={"Cache-Control": "no-store"},
        )

    async def offer(request):
        body = await request.json()
        if not isinstance(body, dict) or any(
            not isinstance(body.get(key), str) for key in ("camera", "sdp", "type")
        ):
            raise ValueError("Expected a camera and WebRTC offer")
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
    app.router.add_get("/api/nodes/{node}/log", node_log)
    app.router.add_get("/api/cameras/{camera}/log", camera_log)
    app.router.add_get("/api/robots/{robot}/log", robot_log)
    app.router.add_post("/api/action", action)
    app.router.add_post("/api/offer", offer)
    app.router.add_static("/static", static)
    return app


def serve(
    role,
    port,
    endpoint_port,
    directory,
    *,
    host="127.0.0.1",
    ssl=False,
    ssl_cert=None,
    ssl_key=None,
):
    import fcntl

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "service.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another service is using this state directory") from exc
        context = dashboard_tls(directory, host, ssl_cert, ssl_key) if ssl else None
        service = Application(role, directory, endpoint_port)
        controller_host = dashboard_client_host(host, ssl_cert if ssl else None)
        if ":" in controller_host:
            controller_host = f"[{controller_host}]"
        service.controller_server = f"{'https' if ssl else 'http'}://{controller_host}:{port}"
        if ssl:
            service.controller_certificate = str(ssl_cert or directory / "https" / "endpoint.pem")
        web.run_app(
            create_app(service, host),
            host=host,
            port=port,
            ssl_context=context,
            access_log=None,
            shutdown_timeout=5,
        )
