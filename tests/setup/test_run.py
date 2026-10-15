# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run logging must preserve failures, shutdown output and separate node sessions."""

import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    shutil.copy(Path(__file__).parents[2] / "run.sh", root)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts/select_runtime.py").write_text(
        "import os; print(os.environ.get('TEST_CAMERA_SDK', '5'))\n"
    )
    module = root / "telesurgery.py"
    module.write_text(
        "import os, signal, sys\n"
        "if os.environ.get('WAIT_FOR_STOP'):\n"
        "    def stop(signum, frame):\n"
        "        print('Shutdown complete')\n"
        "        sys.exit(0)\n"
        "    signal.signal(signal.SIGINT, stop)\n"
        "print('Application ready')\n"
        "print('Runtime:', os.environ['TELESURGERY_SDK'])\n"
        "print('Diagnostic output', file=sys.stderr)\n"
        "if os.environ.get('WAIT_FOR_STOP'): signal.pause()\n"
        "sys.exit(int(os.environ.get('EXIT_CODE', '0')))\n"
    )
    monkeypatch.setenv("TELESURGERY_PYTHON", sys.executable)
    return root, ["bash", str(root / "run.sh")]


def test_node_logs_are_separate_and_preserve_failures(launcher, monkeypatch):
    root, command = launcher
    monkeypatch.setenv("EXIT_CODE", "7")
    for sim in (None, "mira", "franka", "mira"):
        options = ["--sim", sim] if sim else []
        result = subprocess.run(
            [*command, "node", "--patient", "localhost", *options],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 7
        assert "Application ready" in result.stdout
        assert "Diagnostic output" in result.stdout
    logs = list((root / "workspace/logs").glob("*.log"))
    assert len(logs) == 4
    for sim in (None, "mira", "franka"):
        name = socket.gethostname() + (f"-{sim}" if sim else "")
        assert any(path.name.startswith(f"node-{name}-") for path in logs)
    for path in logs:
        assert "Application ready" in path.read_text()
        assert "Diagnostic output" in path.read_text()
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("assignment", [False, True])
def test_custom_workspace_and_node_name(launcher, assignment):
    root, command = launcher
    workspace = root / "custom workspace"
    args = {"--workspace": str(workspace), "--name": "room-camera"}
    options = []
    for key, value in args.items():
        options.extend([f"{key}={value}"] if assignment else [key, value])
    result = subprocess.run(
        [*command, "node", "--patient", "localhost", *options],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout
    assert len(list((workspace / "logs").glob("node-room-camera-*.log"))) == 1
    assert not (root / "workspace").exists()


def test_ctrl_c_retains_shutdown_output(launcher, monkeypatch):
    root, command = launcher
    monkeypatch.setenv("WAIT_FOR_STOP", "1")
    process = subprocess.Popen(
        [*command, "surgeon", "--port", "8012"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        # stdout is piped: readiness must arrive before the application exits.
        ready = b""
        deadline = time.monotonic() + 10
        while b"Application ready" not in ready:
            assert select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))[0]
            chunk = os.read(process.stdout.fileno(), 4096)
            assert chunk, "Application exited before readiness"
            ready += chunk
        os.killpg(process.pid, signal.SIGINT)
        output, _ = process.communicate(timeout=10)
        assert process.returncode == 0
        assert "Shutdown complete" in output
        (log,) = (root / "workspace/logs").glob("surgeon-8012-*.log")
        assert "Shutdown complete" in log.read_text()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def test_help_does_not_create_logs(launcher):
    root, command = launcher
    for options in (["--help"], ["node", "--help"]):
        subprocess.run([*command, *options], check=True, capture_output=True, timeout=10)
    assert not (root / "workspace").exists()


@pytest.mark.parametrize(
    "options,expected",
    [
        (["node", "--patient", "localhost"], "4"),
        (["--sdk", "5", "node", "--patient", "localhost"], "4"),
        (["node", "--patient", "localhost", "--sim=mira"], "5"),
        (["node", "--patient", "localhost", "--sim", "franka"], "5"),
        (["patient"], "5"),
        (["surgeon"], "5"),
    ],
)
def test_only_physical_nodes_select_detected_camera_runtime(
    launcher, monkeypatch, options, expected
):
    _, command = launcher
    monkeypatch.setenv("TEST_CAMERA_SDK", "4")
    result = subprocess.run([*command, *options], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert f"Runtime: {expected}" in result.stdout


def test_camera_selection_without_native_environment_ignores_path_python(launcher, monkeypatch):
    root, command = launcher
    tools = root / "conda/bin"
    tools.mkdir(parents=True)
    python = tools / "python3"
    python.write_text("#!/bin/sh\necho 'PATH Python has no yaml module' >&2\nexit 1\n")
    python.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("TEST_CAMERA_SDK", "4")
    result = subprocess.run(
        [*command, "node", "--patient", "localhost"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stdout
    assert "Runtime: 4" in result.stdout
