# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Launch a dashboard or an enrolled device node."""

import argparse
import asyncio
import json
import logging
import os
import re
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def node_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise argparse.ArgumentTypeError("use 1–64 letters, digits, dots, underscores or hyphens")
    return value


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in {"status", "stop"}:
        from telesurgery.application.lifecycle import main as manage

        return manage(argv)
    parser = argparse.ArgumentParser(prog="./run.sh", description="Holoscan telesurgery")
    commands = parser.add_subparsers(dest="role", required=True)
    commands.add_parser("status", help="list running local services")
    commands.add_parser("stop", help="stop local services gracefully")
    for role, default_port in (("patient", 8000), ("surgeon", 8002)):
        command = commands.add_parser(role, help=f"start the {role} dashboard")
        command.add_argument(
            "--host", default="127.0.0.1", help="dashboard bind address (default: 127.0.0.1)"
        )
        command.add_argument("--ssl", action="store_true", help="serve the dashboard over HTTPS")
        command.add_argument("--ssl-cert", type=Path, help="PEM certificate for --ssl")
        command.add_argument("--ssl-key", type=Path, help="PEM private key for --ssl")
        command.add_argument(
            "--port",
            type=port,
            default=default_port,
            help=f"dashboard port (default: {default_port})",
        )
        command.add_argument(
            "--workspace",
            type=Path,
            default=Path("workspace"),
            help="workspace directory (default: ./workspace)",
        )
        if role == "patient":
            command.add_argument(
                "--endpoint-port",
                type=port,
                default=7447,
                help="application endpoint for surgeons and nodes",
            )
    node = commands.add_parser("node", help="run a device service without a dashboard")
    node.add_argument(
        "--patient", required=True, help="patient hostname or IP (default port: 7447)"
    )
    node.add_argument(
        "--name", type=node_name, help="node name (default: hostname plus environment)"
    )
    node.add_argument(
        "--workspace",
        type=Path,
        default=Path("workspace"),
        help="workspace directory (default: ./workspace)",
    )
    node.add_argument("--port", type=port, default=0, help="direct video port (default: automatic)")
    node.add_argument(
        "--sim", choices=["mira", "franka", "versius"], help="start a simulation on this node"
    )
    node.add_argument("--sim-gui", action="store_true", help="open the Isaac Sim window for --sim")
    node.add_argument(
        "--profile",
        action="append",
        choices=["mira", "franka", "none"],
        help="physical device profile; repeat for multiple devices (saved per node)",
    )
    node.add_argument(
        "--mira-api",
        type=Path,
        help="vendor executable (default: WORKSPACE/mira-api; prompts if missing)",
    )
    node.add_argument(
        "--mira-pod-interface",
        help="node's POD-facing IPv4 address (first-use default: 192.168.0.1)",
    )
    node.add_argument(
        "--franka-address", help="Franka IPv4 address (first-use default: 172.16.0.3)"
    )
    commands.add_parser("doctor", help="check the SDK and GPU video codec")
    controller = commands.add_parser(
        "controller", help="open native robot controls on the surgeon desktop"
    )
    controller.add_argument(
        "--server", default="http://127.0.0.1:8002", help="surgeon dashboard URL"
    )
    controller.add_argument("--robot", help="initial robot ID (otherwise choose in the window)")
    controller.add_argument(
        "--certificate", type=Path, help="trusted certificate for an HTTPS dashboard"
    )
    args = parser.parse_args(argv)
    if args.role in {"patient", "surgeon"}:
        if bool(args.ssl_cert) != bool(args.ssl_key):
            parser.error("--ssl-cert and --ssl-key must be supplied together")
        if args.ssl_cert and not args.ssl:
            parser.error("--ssl-cert and --ssl-key require --ssl")
    if getattr(args, "sim_gui", False) and not args.sim:
        parser.error("--sim-gui requires --sim")
    if (
        args.role == "node"
        and args.sim
        and (args.profile or args.mira_api or args.mira_pod_interface or args.franka_address)
    ):
        parser.error("physical device profiles cannot be combined with --sim")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("aioice").setLevel(logging.WARNING)
    if args.role not in {"doctor", "controller"}:
        args.workspace = args.workspace.expanduser().resolve()
        os.environ["TELESURGERY_WORKSPACE"] = str(args.workspace)
    try:
        if args.role == "controller":
            from telesurgery.controller.client import Client

            Client(args.server, args.certificate).action("controller.open", {"id": args.robot})
        elif args.role == "doctor":
            from telesurgery_core.video.codecs import probe
            from telesurgery_core.video.config import Config
            from telesurgery_runtime.backends.sdk import require_sdk

            print(f"Holoscan {require_sdk().__version__}")
            print(json.dumps(probe(Config(codec="h264")), indent=2))
        elif args.role == "node":
            import fcntl

            from telesurgery.application.lifecycle import register
            from telesurgery.nodes.profiles import prepare

            name = args.name or socket.gethostname() + (f"-{args.sim}" if args.sim else "")
            directory = args.workspace / "nodes" / name
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (directory / "service.lock").open("w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError(
                        f"Node {name} is already running; choose another --name"
                    ) from exc
                if not args.sim:
                    prepare(
                        args.workspace,
                        directory,
                        args.profile,
                        mira_api=args.mira_api,
                        pod_interface=args.mira_pod_interface,
                        franka_ip=args.franka_address,
                    )
                from telesurgery.nodes.client import run_service

                log = RotatingFileHandler(directory / "node.log", maxBytes=1_048_576, backupCount=1)
                log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                logging.getLogger().addHandler(log)
                pid = directory / "node.pid"
                pid.write_text(str(os.getpid()))
                try:
                    with register(directory, "node", name):
                        asyncio.run(
                            run_service(
                                directory, args.patient, name, args.port, args.sim, args.sim_gui
                            )
                        )
                except asyncio.CancelledError:
                    pass
                finally:
                    pid.unlink(missing_ok=True)
                    logging.getLogger().removeHandler(log)
                    log.close()
        else:
            from telesurgery.server.http import serve

            if args.role == "patient" and args.port == args.endpoint_port:
                parser.error("browser and application endpoint ports must differ")
            directory = args.workspace / f"{args.role}-{args.port}"
            serve(
                args.role,
                args.port,
                getattr(args, "endpoint_port", 7447),
                directory,
                host=args.host,
                ssl=args.ssl,
                ssl_cert=args.ssl_cert,
                ssl_key=args.ssl_key,
            )
        return 0
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        logging.error("%s", exc)
        return 1
