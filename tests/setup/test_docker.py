# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""External dashboard certificates must be mounted read-only with correct quoting."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("assignment", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
def test_dashboard_certificate_mounts(tmp_path, monkeypatch, assignment, terminal):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "dependencies").mkdir()
    shutil.copy(Path(__file__).parents[2] / "run.sh", root / "run.sh")
    shutil.copy(Path(__file__).parents[2] / "scripts/docker.sh", root / "scripts/docker.sh")
    (root / "dependencies/sdk5.toml").write_text('git = "https://example.invalid/sdk"\n')
    tools = tmp_path / "bin"
    tools.mkdir()
    records = tmp_path / "calls.jsonl"
    runtimes = "runc" if assignment else "runc\nnvidia"
    (tools / "docker").write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"with open({str(records)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        f"if sys.argv[1] == 'info': print({runtimes!r})\n"
        "if sys.argv[1] == 'build': print('Build output', file=sys.stderr)\n"
        "if sys.argv[1] == 'run': print('Run output')\n"
    )
    (tools / "docker").chmod(0o755)
    (tools / "chronyc").write_text("#!/bin/sh\nexit 0\n")
    (tools / "chronyc").chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    cert, key = tmp_path / "server cert.pem", tmp_path / "server key.pem"
    cert.touch()
    key.touch()
    workspace = tmp_path / "saved workspace"
    options = []
    for flag, path in [("--ssl-cert", cert), ("--ssl-key", key), ("--workspace", workspace)]:
        options.extend([f"{flag}={path}"] if assignment else [flag, str(path)])
    launcher = ["bash", str(root / "run.sh"), "--docker", "patient", "--ssl", *options]
    if terminal:
        launcher = ["script", "-qec", shlex.join(launcher), "/dev/null"]
    subprocess.run(
        launcher,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    command = json.loads(records.read_text().splitlines()[-1])
    assert command[0] == "run"
    assert ("--runtime=nvidia" in command) is not assignment
    assert "PYTHONUNBUFFERED=1" in command
    assert ("-it" in command) is terminal
    for path in [cert, key]:
        assert f"{path}:{path}:ro" in command
    assert f"{workspace}:{workspace}" in command
    assert workspace.is_dir()
    assert not (root / "workspace").exists()
    assert command[-len(options) :] == options
    (log,) = (workspace / "logs").glob("patient-8000-*.log")
    assert "Build output" in log.read_text()
    assert "Run output" in log.read_text()
