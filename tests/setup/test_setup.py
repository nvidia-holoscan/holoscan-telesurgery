# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Exercise the Bash installer without changing host packages or clock services."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "checkout with spaces"
    tools = root / "build/tools/bin"
    tools.mkdir(parents=True)
    shutil.copy(Path(__file__).parents[2] / "setup.sh", root)
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("SETUP_CALLS", str(calls))
    stub = (
        f"#!{sys.executable}\n"
        + """
import json
import os
import sys
from pathlib import Path

command = [Path(sys.argv[0]).name, *sys.argv[1:]]
if command[0] == "sudo":
    command = command[1:]
if command[0] == "build_franka.sh":
    assert os.environ["UV_PROJECT_ENVIRONMENT"] == str(
        Path.cwd() / (".venv-sdk" + os.environ["TELESURGERY_SDK"])
    )
with Path(os.environ["SETUP_CALLS"]).open("a") as log:
    log.write(json.dumps({"command": command, "sdk": os.environ["TELESURGERY_SDK"]}) + "\\n")
if os.environ.get("SETUP_FAIL") in command:
    sys.exit("Setup fixture failure")
if "scripts/setup_cache.py" in command and "check" in command:
    sys.exit(0 if os.environ.get("SETUP_CACHE_HIT") and "--force" not in command else 1)
if command[0] == "dpkg-query":
    if command[-1] in os.environ.get("SETUP_MISSING_PACKAGES", "libegl1").split():
        sys.exit(1)
    print("installed")
elif command[0] == "nvcc":
    print("Cuda compilation tools, release 13.0")
"""
    )
    for name in ("python3", "uv", "nvcc", "c++", "dpkg-query", "apt-get", "sudo"):
        path = tools / name
        path.write_text(stub)
        path.chmod(0o755)
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "build_franka.sh").symlink_to(tools / "python3")
    for sdk in (4, 5):
        environment = root / f".venv-sdk{sdk}/bin"
        environment.mkdir(parents=True)
        (environment / "python").symlink_to(tools / "python3")

    def invoke(*args):
        result = subprocess.run(
            ["bash", str(root / "setup.sh"), *args], cwd=tmp_path, capture_output=True, text=True
        )
        records = (
            [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        )
        return result, records

    return root, invoke


@pytest.mark.parametrize("options,sdk", [((), "5"), (("--sdk", "4"), "4")])
def test_native_setup_selects_sdk_and_installs_only_missing_packages(setup, options, sdk):
    root, invoke = setup
    result, records = invoke(*options)
    assert result.returncode == 0, result.stderr
    assert {item["sdk"] for item in records} == {sdk}
    commands = [
        item["command"]
        for item in records
        if item["command"][0] != "dpkg-query" and "scripts/setup_cache.py" not in item["command"]
    ]
    python = str(root / f".venv-sdk{sdk}/bin/python")
    assert commands == [
        ["nvcc", "--version"],
        ["python3", "scripts/clock_sync.py"],
        ["python3", "scripts/setup_gamepads.py"],
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "--no-remove", "--no-install-recommends", "libegl1"],
        *([["c++", "-std=c++20", "-x", "c++", "-fsyntax-only", "-"]] if sdk == "5" else []),
        [
            "uv",
            "run",
            "--no-project",
            "--python",
            "3.12",
            "python",
            "scripts/builders/dependencies.py",
            "--sdk",
            sdk,
            "--environment",
            str(root / f".venv-sdk{sdk}"),
        ],
        ["python", "scripts/setup_haply.py"],
        ["python", f"scripts/builders/sdk{sdk}.py"],
        ["python", "scripts/builders/codecs.py"],
        [
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--target",
            str(root / "workspace/sim-deps"),
            "pyzmq>=26,<28",
            "websockets>=14,<17",
            "ruckig==0.19.4",
        ],
        [
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--target",
            str(root / "workspace/sim-deps"),
            "--no-deps",
            "trimesh==5.1.0",
        ],
        ["python", "-m", "telesurgery", "doctor"],
    ]
    assert "Setup complete." in result.stdout
    assert records[-1]["command"][:3] == ["python", "scripts/setup_cache.py", "record"]


@pytest.mark.parametrize("sdk", ["4", "5"])
def test_missing_controller_libraries_use_distribution_versions(setup, monkeypatch, sdk):
    _, invoke = setup
    monkeypatch.setenv(
        "SETUP_MISSING_PACKAGES", "libsdl2-2.0-0 python3-tk python3-websocket xvfb xauth"
    )
    result, records = invoke("--sdk", sdk)
    assert result.returncode == 0, result.stderr
    installs = [
        item["command"] for item in records if item["command"][:2] == ["apt-get", "install"]
    ]
    assert installs == [
        [
            "apt-get",
            "install",
            "-y",
            "--no-remove",
            "--no-install-recommends",
            "libsdl2-2.0-0",
            "python3-tk",
            "python3-websocket",
            "xvfb",
            "xauth",
        ]
    ]


@pytest.mark.parametrize("options", [(), ("--profile", "franka")])
def test_docker_setup_prepares_clock_and_gamepad_hotplug(setup, options):
    _, invoke = setup
    result, records = invoke("--docker", *options)
    assert result.returncode == 0, result.stderr
    assert records == [
        {"command": ["python3", "scripts/clock_sync.py"], "sdk": "5"},
        {"command": ["python3", "scripts/setup_gamepads.py"], "sdk": "5"},
    ]


@pytest.mark.parametrize("sdk", ["4", "5"])
def test_franka_profile_builds_in_selected_native_environment(setup, monkeypatch, sdk):
    _, invoke = setup
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/another/environment")
    result, records = invoke("--sdk", sdk, "--profile", "franka")
    assert result.returncode == 0, result.stderr
    assert sum(item["command"] == ["build_franka.sh"] for item in records) == 1
    assert "Building Franka support" in result.stdout


def test_setup_places_simulation_packages_in_custom_workspace(setup, tmp_path):
    _, invoke = setup
    workspace = tmp_path / "custom workspace"
    result, records = invoke("--workspace", str(workspace))
    assert result.returncode == 0, result.stderr
    targets = [item["command"] for item in records if "--target" in item["command"]]
    assert len(targets) == 2
    assert all(str(workspace / "sim-deps") in command for command in targets)


def test_unchanged_setup_keeps_host_checks_and_previous_log(setup, monkeypatch):
    root, invoke = setup
    monkeypatch.setenv("SETUP_CACHE_HIT", "1")
    monkeypatch.setenv("SETUP_MISSING_PACKAGES", "")
    log = root / "build/setup.log"
    log.write_text("Last successful GPU validation\n")
    result, records = invoke()
    assert result.returncode == 0, result.stderr
    assert "already up to date" in result.stdout
    commands = [item["command"] for item in records]
    assert ["python3", "scripts/clock_sync.py"] in commands
    assert ["python3", "scripts/setup_gamepads.py"] in commands
    assert any(command[0] == "dpkg-query" for command in commands)
    assert not any(command[0] in {"uv", "sudo", "apt-get"} for command in commands)
    assert not any("doctor" in command for command in commands)
    assert log.read_text() == "Last successful GPU validation\n"
    assert not list((root / "build/setup").glob("run.*"))


def test_force_reruns_installation_and_validation(setup, monkeypatch):
    _, invoke = setup
    monkeypatch.setenv("SETUP_CACHE_HIT", "1")
    result, records = invoke("--force")
    assert result.returncode == 0, result.stderr
    assert any("scripts/builders/sdk5.py" in item["command"] for item in records)
    assert any("doctor" in item["command"] for item in records)
    assert records[-1]["command"][:3] == ["python", "scripts/setup_cache.py", "record"]


def test_old_compiler_reports_docker_before_downloading_sdk(setup, monkeypatch):
    _, invoke = setup
    monkeypatch.setenv("SETUP_FAIL", "c++")
    result, records = invoke()
    assert result.returncode != 0
    assert "GCC 13+" in result.stderr
    assert "--docker" in result.stderr
    assert not any("scripts/builders/dependencies.py" in item["command"] for item in records)


@pytest.mark.parametrize("component", ["scripts/builders/sdk5.py", "build_franka.sh"])
def test_failed_build_stops_setup_and_reports_log(setup, monkeypatch, component):
    root, invoke = setup
    monkeypatch.setenv("SETUP_FAIL", component)
    result, records = invoke("--profile", "franka")
    assert result.returncode != 0
    assert "Setup fixture failure" in result.stderr
    assert str(root / "build/setup.log") in result.stderr
    assert component in records[-1]["command"]
    assert "Setup complete" not in result.stdout


@pytest.mark.parametrize(
    "options",
    [("--sdk",), ("--sdk", "6"), ("--time-server", "host"), ("--profile",), ("--profile", "bad")],
)
def test_invalid_options_do_not_change_host(setup, options):
    _, invoke = setup
    result, records = invoke(*options)
    assert result.returncode != 0
    assert records == []
