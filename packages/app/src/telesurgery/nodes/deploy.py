# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deploy this uv workspace to an SSH node, using the user's existing SSH setup."""

import asyncio
import io
import os
import re
import shlex
import tarfile
from pathlib import Path

import yaml
from telesurgery_core.diagnostics.logs import read_log

# PID files identify only this installation's managed node, never unrelated Python services.
STOP_NODE = """
import os, signal, time
from pathlib import Path
root = Path.cwd()
record = root / 'node.pid'
if record.exists():
    pid = int(record.read_text())
    process = Path(f'/proc/{pid}/cmdline')
    def owned():
        try:
            args = process.read_bytes().decode().split('\\0')
            return (args[0].startswith(str(root / '.venv-sdk'))
                    and args[1:4] == ['-m', 'telesurgery', 'node'])
        except (FileNotFoundError, ProcessLookupError):
            return False
    if owned():
        os.kill(pid, signal.SIGTERM)
        for _ in range(150):
            if not owned():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('The previous node service did not stop; see node.log')
"""


def workspace_root():
    if os.environ.get("TELESURGERY_WORKSPACE"):
        return Path(os.environ["TELESURGERY_WORKSPACE"])
    for parent in Path(__file__).resolve().parents:
        if (parent / "uv.lock").is_file() and (parent / "packages").is_dir():
            return parent
    raise RuntimeError("Node deployment needs the application workspace")


async def deploy(target, config, sdk, log):
    if (
        not isinstance(target, str)
        or not re.fullmatch(r"[A-Za-z0-9_.@:-]+", target)
        or target.startswith("-")
    ):
        raise ValueError("Use an SSH hostname, alias, or user@host")
    if sdk not in {4, 5}:
        raise ValueError("Choose SDK 4 or SDK 5")
    root = workspace_root()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for name in (
            "packages",
            "scripts",
            "native",
            "dependencies",
            "pyproject.toml",
            "uv.lock",
            "setup.sh",
            "run.sh",
            "README.md",
            "LICENSE",
        ):
            path = root / name
            for item in [path] if path.is_file() else path.rglob("*"):
                if (
                    item.is_file()
                    and not any(p in {"__pycache__", ".venv"} for p in item.parts)
                    and item.suffix not in {".so", ".pyc"}
                ):
                    tar.add(item, arcname=str(item.relative_to(root)), recursive=False)
        for filename, settings in {
            "node.yaml": config,
            "environment.yaml": {"environment": config.get("environment"), "gui": False},
        }.items():
            data = yaml.safe_dump(settings, sort_keys=False).encode()
            info = tarfile.TarInfo(filename)
            info.size, info.mode = len(data), 0o600
            tar.addfile(info, io.BytesIO(data))
    # One isolated install per registered node; no assumption about a Projects checkout.
    name = shlex.quote(config["id"])
    command = (
        f'install -d -m 700 "$HOME/.local/share/holoscan-telesurgery/{name}" && '
        f'cd "$HOME/.local/share/holoscan-telesurgery/{name}" && '
        f"tar xzf - && python3 -c {shlex.quote(STOP_NODE)} && ./setup.sh --sdk {sdk} && "
        "echo 'Starting node service…' && "
        f'sh -c "nohup ./run.sh --sdk {sdk} node --config node.yaml > node.log 2>&1 < /dev/null &"'
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            "ssh",
            "-A",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            target,
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=output,
            stderr=output,
        )
        try:
            await process.communicate(archive.getvalue())
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()
    if process.returncode:
        raise RuntimeError(f"Node setup failed. {read_log(log)['text'][-1500:]}")
