# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Physical profiles use a local executable and never start a robot controller."""

import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from telesurgery.application.cli import main
from telesurgery.nodes.profiles import devices, prepare
from telesurgery_core.configuration import load, save
from telesurgery_robots.mira import binary
from telesurgery_robots.mira.controller import MiraController


def elf(machine):
    return (
        b"\x7fELF\x02\x01\x01" + bytes(9) + b"\x03\x00" + machine.to_bytes(2, "little") + bytes(44)
    )


@pytest.fixture
def executable(tmp_path, monkeypatch):
    monkeypatch.setattr(binary.platform, "machine", lambda: "aarch64")
    path = tmp_path / "MiraAPI-linux-arm64-2025-07-18"
    path.write_bytes(elf(183))
    return path


@pytest.mark.parametrize("machine,code", [("aarch64", 183), ("x86_64", 62)])
def test_install_binary_into_workspace_and_reuse(tmp_path, monkeypatch, machine, code):
    monkeypatch.setattr(binary.platform, "machine", lambda: machine)
    source = tmp_path / "vendor-api"
    source.write_bytes(elf(code))
    workspace = tmp_path / "workspace"
    node = workspace / "nodes/physical"
    prepare(workspace, node, ["mira"], mira_api=source)
    (robot,) = devices(node)
    installed = workspace / "mira-api"
    assert Path(robot["controller"]["executable"]) == installed
    assert installed.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(installed.stat().st_mode) == 0o700
    assert robot["connection_enabled"] is False
    assert robot["controller"]["sha256"] == binary.checksum(source)
    assert f"{installed}:/opt/mira-api:ro" in MiraController(robot, node).command()
    assert not (workspace / "vendor").exists()
    source.unlink()
    save(node / "connections.yaml", {"mira": True})
    prepare(workspace, node)
    assert devices(node)[0]["connection_enabled"] is True
    other = workspace / "nodes/other"
    prepare(workspace, other, ["mira"])
    assert devices(other)[0]["connection_enabled"] is False
    prepare(workspace, node, ["mira"], pod_interface="192.168.0.5")
    assert devices(node)[0]["connection_enabled"] is False


def test_default_binary_and_multiple_profiles(tmp_path, executable):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable.rename(workspace / "mira-api")
    node = workspace / "nodes/physical"
    save(node / "devices.yaml", {"cameras": [{"id": "camera"}], "robots": [{"id": "manual"}]})
    original = (node / "devices.yaml").read_bytes()
    prepare(workspace, node, ["mira", "franka"], franka_ip="172.16.0.3")
    assert [r["kind"] for r in devices(node)] == ["mira", "franka"]
    prepare(workspace, node, ["franka"])
    assert [r["kind"] for r in devices(node)] == ["franka"]
    prepare(workspace, node, ["none"])
    prepare(workspace, node)
    assert not devices(node)
    assert (node / "devices.yaml").read_bytes() == original


def test_first_use_prompts_once_and_saves_default(tmp_path, executable, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    prompt = Mock(return_value=str(executable))
    monkeypatch.setattr("builtins.input", prompt)
    directory = tmp_path / "nodes/test"
    prepare(tmp_path, directory, ["mira"])
    assert (tmp_path / "mira-api").read_bytes() == executable.read_bytes()
    executable.unlink()
    prepare(tmp_path, directory, ["mira"])
    prompt.assert_called_once()
    assert devices(directory)[0]["connection_enabled"] is False


def test_changed_binary_requires_node_restart_and_disconnects(tmp_path, executable):
    directory = tmp_path / "nodes/test"
    prepare(tmp_path, directory, ["mira"], mira_api=executable)
    controller = MiraController(devices(directory)[0], directory)
    save(directory / "connections.yaml", {"mira": True})
    (tmp_path / "mira-api").write_bytes(elf(183) + b"new version")
    with pytest.raises(ValueError, match="restart the node"):
        controller.command()
    prepare(tmp_path, directory)
    assert devices(directory)[0]["connection_enabled"] is False
    settings = load(tmp_path / "profiles/mira.yaml")["robot"]["controller"]
    assert settings["sha256"] == binary.checksum(tmp_path / "mira-api")


def test_conflicts_and_invalid_binary_preserve_previous_selection(tmp_path, executable):
    node = tmp_path / "nodes/one"
    prepare(tmp_path, node, ["franka"], franka_ip="172.16.0.3")
    before = (node / "profiles.yaml").read_bytes()
    executable.write_text("invalid")
    with pytest.raises(ValueError, match="ELF"):
        prepare(tmp_path, node, ["mira"], mira_api=executable)
    assert (node / "profiles.yaml").read_bytes() == before
    executable.write_bytes(elf(183))
    save(node / "devices.yaml", {"robots": [{"id": "mira", "kind": "mira"}]})
    with pytest.raises(ValueError, match="Duplicate robot"):
        prepare(tmp_path, node, ["mira"], mira_api=executable)
    assert (node / "profiles.yaml").read_bytes() == before
    assert not (tmp_path / "profiles/mira.yaml").exists()


def test_wrong_architecture_is_rejected(tmp_path, executable, monkeypatch):
    monkeypatch.setattr(binary.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="x86_64 ELF"):
        binary.install(tmp_path, executable)
    monkeypatch.setattr(binary.platform, "machine", lambda: "riscv64")
    with pytest.raises(ValueError, match="architecture"):
        binary.install(tmp_path, executable)
    assert not (tmp_path / "mira-api").exists()


@pytest.mark.parametrize(
    "names,options,error",
    [
        (["mira", "mira"], {}, "each profile once"),
        (["none", "mira"], {}, "used alone"),
        ([], {"mira_api": Path("missing")}, "require --profile mira"),
        (["mira"], {"pod_interface": "127.0.0.1"}, "non-loopback"),
        (["mira"], {}, "copy the binary to workspace/mira-api"),
    ],
)
def test_profile_input_errors(tmp_path, monkeypatch, names, options, error):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match=error):
        prepare(tmp_path, tmp_path / "nodes/one", names, **options)


def test_cli_prepares_profiles_before_running_node(tmp_path, monkeypatch, executable):
    monkeypatch.setenv("TELESURGERY_WORKSPACE", str(tmp_path))
    calls = []

    async def run_service(directory, *args):
        calls.append(devices(directory))

    monkeypatch.setitem(
        sys.modules, "telesurgery.nodes.client", SimpleNamespace(run_service=run_service)
    )
    options = ["node", "--patient", "patient", "--workspace", str(tmp_path), "--name", "test"]
    assert main([*options, "--profile", "mira", "--mira-api", str(executable)]) == 0
    assert calls[0][0]["kind"] == "mira"
    assert calls[0][0]["connection_enabled"] is False
    assert main(options) == 0
    assert calls[1] == calls[0]
    with pytest.raises(SystemExit):
        main([*options, "--profile", "mira", "--sim", "mira"])
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_profile_connection_choice_uses_node_state(tmp_path):
    from telesurgery.nodes.service import NodeService

    directory = tmp_path / "nodes/one"
    prepare(tmp_path, directory, ["franka"], franka_ip="172.16.0.3")
    node = object.__new__(NodeService)
    node.local = SimpleNamespace(
        directory=directory, simulation=None, robots={"franka": devices(directory)[0]}
    )
    node.robots = SimpleNamespace(sync=Mock())
    await node.set_connection("franka", True)
    assert devices(directory)[0]["connection_enabled"] is True
    await node.set_connection("franka", False)
    assert devices(directory)[0]["connection_enabled"] is False
    assert not (directory / "devices.yaml").exists()


@pytest.mark.parametrize("answer", ["", EOFError()])
def test_cancelled_prompt_leaves_no_profile(tmp_path, monkeypatch, answer):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    prompt = (
        Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    )
    monkeypatch.setattr("builtins.input", prompt)
    with pytest.raises(ValueError, match="--mira-api PATH"):
        prepare(tmp_path, tmp_path / "nodes/test", ["mira"])
    assert not (tmp_path / "profiles/mira.yaml").exists()


def test_profiles_join_physical_inventory_and_reject_conflicts(tmp_path, monkeypatch):
    from telesurgery.nodes import local

    monkeypatch.setattr(local, "camera_devices", lambda: [])
    monkeypatch.setattr(local, "enrich", lambda cameras: None)
    monkeypatch.setattr(local, "discover_hsb", lambda: {})
    directory = tmp_path / "nodes/test"
    prepare(tmp_path, directory, ["franka"], franka_ip="172.16.0.3")
    camera = {"id": "configured-camera"}
    manual = {"id": "other", "kind": "mira", "connection_enabled": False}
    save(directory / "devices.yaml", {"cameras": [camera], "robots": [manual]})
    cameras, robots = local.discover(directory)
    assert cameras == [camera]
    assert robots[0] == manual
    assert robots[1]["id"] == "franka" and robots[1]["connection_enabled"] is False
    save(directory / "devices.yaml", {"robots": [{"id": "franka"}]})
    with pytest.raises(ValueError, match="Duplicate robot"):
        local.discover(directory)


@pytest.mark.parametrize(
    "robots",
    [None, {}, "franka", [None], ["franka"], [{}], [{"id": []}], [{"id": 1}], [{"id": ""}]],
)
def test_invalid_manual_robots_report_configuration_error(tmp_path, monkeypatch, caplog, robots):
    from telesurgery.nodes import local

    monkeypatch.setenv("TELESURGERY_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(local, "camera_devices", lambda: [])
    monkeypatch.setattr(local, "enrich", lambda cameras: None)
    monkeypatch.setattr(local, "discover_hsb", lambda: {})
    directory = tmp_path / "nodes/test"
    prepare(tmp_path, directory, ["franka"])
    save(directory / "connections.yaml", {"franka": True})
    saved = {
        path: path.read_bytes()
        for path in [
            directory / "profiles.yaml",
            directory / "connections.yaml",
            tmp_path / "profiles/franka.yaml",
        ]
    }
    save(directory / "devices.yaml", {"robots": robots})
    with pytest.raises(ValueError, match="devices.yaml"):
        prepare(tmp_path, directory, ["franka"], franka_ip="172.16.0.8")
    with pytest.raises(ValueError, match="devices.yaml"):
        local.discover(directory)
    assert (
        main(["node", "--patient", "unused", "--workspace", str(tmp_path), "--name", "test"]) == 1
    )
    assert "devices.yaml" in caplog.text
    assert all(path.read_bytes() == content for path, content in saved.items())


def test_franka_default_and_saved_address_precedence(tmp_path):
    directory = tmp_path / "nodes/one"
    prepare(tmp_path, directory, ["franka"])
    assert devices(directory)[0]["address"] == "172.16.0.3"
    assert devices(directory)[0]["connection_enabled"] is False
    prepare(tmp_path, directory, ["franka"], franka_ip="172.16.0.8")
    assert devices(directory)[0]["address"] == "172.16.0.8"
    prepare(tmp_path, directory, ["franka"])
    assert devices(directory)[0]["address"] == "172.16.0.8"
    prepare(tmp_path, tmp_path / "nodes/two", ["franka"])
    assert devices(tmp_path / "nodes/two")[0]["address"] == "172.16.0.8"
