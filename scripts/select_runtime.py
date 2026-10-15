#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Select capture support before starting native Python or building a container."""

import argparse
import socket
import sys
from pathlib import Path

# Run with the host Python before the workspace packages or any SDK are installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/core/src"))
from telesurgery_core.hsb import configured, discover  # noqa: E402


def select(workspace, name=None, *, all_nodes=False, timeout=2.5):
    nodes = workspace / "nodes"
    directories = list(nodes.iterdir()) if all_nodes and nodes.is_dir() else []
    if not all_nodes:
        directories = [nodes / (name or socket.gethostname())]
    if any(configured(directory) for directory in directories if directory.is_dir()):
        return "4"
    return "4" if discover(timeout, first=True) else "5"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    parser.add_argument("--name")
    parser.add_argument("--all-nodes", action="store_true")
    args = parser.parse_args()
    try:
        print(select(args.workspace.expanduser().resolve(), args.name, all_nodes=args.all_nodes))
    except ImportError:
        parser.exit(1, "Camera discovery requires host dependencies; run ./setup.sh first.\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot select camera support: {exc}\n")


if __name__ == "__main__":
    main()
