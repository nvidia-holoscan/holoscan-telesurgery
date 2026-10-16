# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Use one versioned image and preserve device, certificate and terminal access."""

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def docker_launcher(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "dependencies").mkdir()
    shutil.copy(Path(__file__).parents[2] / "run.sh", root / "run.sh")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts/select_runtime.py").write_text(
        "import os; print(os.environ.get('TEST_CAMERA_SDK', '5'))\n"
    )
    shutil.copy(Path(__file__).parents[2] / "scripts/docker.sh", root / "scripts/docker.sh")
    shutil.copy(Path(__file__).parents[2] / "pyproject.toml", root)
    for sdk in (4, 5):
        (root / f"dependencies/sdk{sdk}.toml").write_text(
            '[holoscan]\ngit = "https://example.invalid/sdk"\n'
        )
    tools = tmp_path / "bin"
    tools.mkdir()
    records = tmp_path / "calls.jsonl"
    (tools / "docker").write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        f"with open({str(records)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1] == 'info': print(os.environ.get('TEST_RUNTIMES', 'runc\\nnvidia'))\n"
        "if sys.argv[1] == 'build': print('Build output', file=sys.stderr)\n"
        "if sys.argv[1] == 'run': print('Run output')\n"
    )
    (tools / "docker").chmod(0o755)
    (tools / "chronyc").write_text("#!/bin/sh\nexit 0\n")
    (tools / "chronyc").chmod(0o755)
    (tools / "ssh-add").write_text("#!/bin/sh\nexit 0\n")
    (tools / "ssh-add").chmod(0o755)
    (tools / "stat").write_text(
        '#!/bin/sh\nif [ "$3" = /var/run/docker.sock ]; then echo 1000; '
        'else exec /usr/bin/stat "$@"; fi\n'
    )
    (tools / "stat").chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    agent = socket.socket(socket.AF_UNIX)
    agent.bind(str(tmp_path / "agent"))
    monkeypatch.setenv("SSH_AUTH_SOCK", str(tmp_path / "agent"))
    try:
        yield root, records
    finally:
        agent.close()


@pytest.mark.parametrize("assignment", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
def test_dashboard_certificate_mounts(docker_launcher, tmp_path, monkeypatch, assignment, terminal):
    root, records = docker_launcher
    monkeypatch.setenv("TEST_RUNTIMES", "runc" if assignment else "runc\nnvidia")
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


@pytest.mark.parametrize("sdk,suffix", [(4, "-sdk4"), (5, "")])
@pytest.mark.parametrize(
    "options,role",
    [
        (["patient"], "dashboard"),
        (["surgeon"], "dashboard"),
        (["doctor"], "dashboard"),
        (["node", "--patient", "localhost"], "node-real"),
        (["node", "--patient", "localhost", "--sim", "mira"], "node-sim"),
        (["node", "--patient", "localhost", "--sim=franka"], "node-sim"),
    ],
)
def test_shared_image_and_role_mounts(docker_launcher, options, role, sdk, suffix):
    root, records = docker_launcher
    # The tag follows project metadata, rather than a second hard-coded version.
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.7"\n')
    subprocess.run(
        ["bash", str(root / "run.sh"), "--docker", "--sdk", str(sdk), *options],
        check=True,
        capture_output=True,
        timeout=10,
    )
    commands = [json.loads(line) for line in records.read_text().splitlines()]
    build = next(c for c in commands if c[0] == "build")
    assert build[build.index("--network") + 1] == "host"
    image = f"holoscan-telesurgery:0.1.7{suffix}"
    assert "--target" not in build
    assert build[build.index("--tag") + 1] == image
    assert "--ssh" not in build
    assert "--secret" not in build
    run = commands[-1]
    assert run[-len(options) - 1 :] == [image, *options]
    assert ("SYS_NICE" in run) is (role == "node-real")
    assert ("/var/run/docker.sock:/var/run/docker.sock" in run) is (role != "dashboard")
    if role != "node-real":
        if options[0] != "surgeon":
            assert "--device" not in run
        else:
            serial = Path("/dev/serial/by-id")
            haply = {
                str(p.resolve())
                for pattern in (
                    "usb-Teensyduino_Haply_inverse3_*",
                    "usb-ZEPHYR_Haply_USB_Transceiver_*",
                )
                for p in serial.glob(pattern)
            }
            assert all(
                run[i + 1] in haply or run[i + 1].startswith("/dev/input/event")
                for i, value in enumerate(run)
                if value == "--device"
            )
        assert "--device-cgroup-rule" not in run
    copies = [c for c in commands if "--entrypoint" in c]
    assert len(copies) == (1 if role == "node-sim" else 0)
    if copies:
        assert copies[0][-4:] == [image, "-r", "/opt/sim-deps/.", "/workspace/sim-deps/"]
    if options[0] != "doctor":
        label = "com.nvidia.telesurgery"
        assert f"{label}.workspace={root / 'workspace'}" in run
        assert f"{label}.role={options[0]}" in run
        assert f"{label}.uid={os.getuid()}" in run
        assert run[run.index("--name") + 1].startswith(f"telesurgery-{options[0]}-")
        assert "TELESURGERY_CONTAINER=1" in run
        assert run[run.index("--stop-timeout") + 1] == "30"


@pytest.mark.parametrize("assignment", [False, True])
def test_vendor_file_outside_checkout_is_mounted_readonly(docker_launcher, tmp_path, assignment):
    root, records = docker_launcher
    executable = tmp_path / "vendor api"
    executable.touch()
    relative = Path("..") / executable.name
    option = [f"--mira-api={relative}"] if assignment else ["--mira-api", str(relative)]
    subprocess.run(
        [
            "bash",
            str(root / "run.sh"),
            "--docker",
            "node",
            "--patient",
            "patient",
            "--profile",
            "mira",
            *option,
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    commands = [json.loads(line) for line in records.read_text().splitlines()]
    command = commands[-1]
    assert f"{executable}:{executable}:ro" in command
    assert command[-1] == (f"--mira-api={executable}" if assignment else str(executable))
    assert "SYS_NICE" in command
    assert not any("--entrypoint" in c for c in commands)


def test_interactive_vendor_prompt_mounts_host_binary(docker_launcher, tmp_path):
    root, records = docker_launcher
    binary = tmp_path / "Mira API"
    binary.touch()
    launcher = [
        "bash",
        str(root / "run.sh"),
        "--docker",
        "node",
        "--patient",
        "patient",
        "--profile=mira",
    ]
    result = subprocess.run(
        ["script", "-qec", shlex.join(launcher), "/dev/null"],
        input=str(binary) + "\n",
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "Path to the vendor MIRA API" in result.stdout
    command = json.loads(records.read_text().splitlines()[-1])
    assert f"{binary}:{binary}:ro" in command
    assert command[-2:] == ["--mira-api", str(binary)]
    # The default executable skips the prompt, even before a profile is saved.
    (root / "workspace/mira-api").touch()
    result = subprocess.run(
        ["script", "-qec", shlex.join(launcher), "/dev/null"],
        input="",
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "Path to the vendor MIRA API" not in result.stdout


def test_explicit_default_binary_remains_writable(docker_launcher, tmp_path):
    root, records = docker_launcher
    workspace = tmp_path / "custom workspace"
    workspace.mkdir()
    binary = workspace / "mira-api"
    binary.touch(mode=0o600)
    subprocess.run(
        [
            "bash",
            str(root / "run.sh"),
            "--docker",
            "node",
            "--patient",
            "patient",
            "--profile",
            "mira",
            "--mira-api",
            str(binary),
            "--workspace",
            str(workspace),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    command = json.loads(records.read_text().splitlines()[-1])
    assert f"{workspace}:{workspace}" in command
    assert f"{binary}:{binary}:ro" not in command


def test_container_identity_uses_canonical_workspace(docker_launcher, tmp_path):
    root, records = docker_launcher
    workspace = tmp_path / "real workspace"
    workspace.mkdir()
    (root / "workspace").symlink_to(workspace, target_is_directory=True)
    names = []
    for arguments in ([], ["--workspace", str(workspace)], ["--port=8004"]):
        subprocess.run(
            ["bash", str(root / "run.sh"), "--docker", "surgeon", *arguments],
            check=True,
            capture_output=True,
            timeout=10,
        )
        command = json.loads(records.read_text().splitlines()[-1])
        names.append(command[command.index("--name") + 1])
        assert f"com.nvidia.telesurgery.workspace={workspace}" in command
    assert names[0] == names[1] != names[2]


@pytest.mark.parametrize("sim", [False, True])
def test_hsb_selects_image_before_build_without_ssh_credentials(docker_launcher, monkeypatch, sim):
    root, records = docker_launcher
    monkeypatch.setenv("TEST_CAMERA_SDK", "4")
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    subprocess.run(
        [
            "bash",
            str(root / "run.sh"),
            "--docker",
            "node",
            "--patient",
            "localhost",
            *(["--sim", "versius"] if sim else []),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    commands = [json.loads(line) for line in records.read_text().splitlines()]
    build = next(c for c in commands if c[0] == "build")
    image = "holoscan-telesurgery:0.1.0" + ("" if sim else "-sdk4")
    assert build[build.index("--tag") + 1] == image
    assert "--ssh" not in build and "--secret" not in build
    assert image in commands[-1]
