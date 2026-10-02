# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Launch one local dashboard or an enrolled device node."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path


def port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(prog="./run.sh", description="Holoscan telesurgery")
    commands = parser.add_subparsers(dest="role", required=True)
    for role, default_port in (("patient", 8000), ("surgeon", 8002)):
        command = commands.add_parser(role, help=f"start the local {role} dashboard")
        command.add_argument(
            "--port",
            type=port,
            default=default_port,
            help=f"local browser port (default: {default_port})",
        )
        command.add_argument("--state-dir", type=Path, help="defaults to runs/ROLE-PORT")
        if role == "patient":
            command.add_argument(
                "--nodes",
                default="",
                metavar="HOST[,HOST…]",
                help="track node services, including offline hosts (default port: 7448)",
            )
            command.add_argument(
                "--endpoint-port",
                type=port,
                default=7447,
                help="application endpoint for surgeons and nodes",
            )
            command.add_argument(
                "--sim",
                choices=["mira", "franka"],
                help="launch an Isaac Sim environment instead of physical discovery",
            )
            command.add_argument(
                "--sim-gui", action="store_true", help="open the Isaac Sim window for --sim"
            )
    node = commands.add_parser("node", help="run a device service without a dashboard")
    location = node.add_mutually_exclusive_group()
    location.add_argument("--config", type=Path, help="connection file supplied by SSH deployment")
    location.add_argument("--state-dir", type=Path, help="defaults to runs/node-PORT")
    node.add_argument("--port", type=port, default=7448, help="node service port (default: 7448)")
    node.add_argument("--sim", choices=["mira", "franka"], help="start a simulation on this node")
    node.add_argument("--sim-gui", action="store_true", help="open the Isaac Sim window for --sim")
    commands.add_parser("doctor", help="check the SDK and GPU video codec")
    args = parser.parse_args(argv)
    if getattr(args, "sim_gui", False) and not args.sim:
        parser.error("--sim-gui requires --sim")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("aioice").setLevel(logging.WARNING)
    try:
        if args.role == "doctor":
            from telesurgery_core.video.codecs import probe
            from telesurgery_core.video.config import Config
            from telesurgery_runtime.sdk import require_sdk

            print(f"Holoscan {require_sdk().__version__}")
            print(json.dumps(probe(Config(codec="h264")), indent=2))
        elif args.role == "node":
            import fcntl

            from telesurgery.nodes.service import run_node
            from telesurgery.nodes.standalone import run_service

            if args.config and args.port != 7448:
                parser.error("--port is only used by standalone nodes")
            directory = (
                args.config.resolve().parent
                if args.config
                else (args.state_dir or Path(f"runs/node-{args.port}")).resolve()
            )
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            with (directory / "service.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                pid = directory / "node.pid"
                pid.write_text(str(os.getpid()))
                try:
                    asyncio.run(
                        run_node(args.config.resolve(), args.sim, args.sim_gui)
                        if args.config
                        else run_service(directory, args.port, args.sim, args.sim_gui)
                    )
                except asyncio.CancelledError:
                    pass
                finally:
                    pid.unlink(missing_ok=True)
        else:
            from telesurgery.server.http import serve

            if args.role == "patient" and args.port == args.endpoint_port:
                parser.error("browser and application endpoint ports must differ")
            if getattr(args, "nodes", "") and args.sim:
                parser.error("--nodes is for physical mode; simulation uses one node")
            directory = (args.state_dir or Path(f"runs/{args.role}-{args.port}")).resolve()
            serve(
                args.role,
                args.port,
                getattr(args, "endpoint_port", 7447),
                directory,
                getattr(args, "sim", None),
                sim_gui=getattr(args, "sim_gui", False),
                nodes=args.nodes.split(",") if getattr(args, "nodes", "") else (),
            )
        return 0
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        logging.error("%s", exc)
        return 1
