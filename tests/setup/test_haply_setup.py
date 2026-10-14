# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Reuse the Hub on newer hosts without omitting the service from Docker images."""

import importlib.util
import io
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "setup_haply", Path(__file__).resolve().parents[2] / "scripts/setup_haply.py"
)
haply = importlib.util.module_from_spec(spec)
spec.loader.exec_module(haply)


@pytest.fixture
def installation(monkeypatch):
    packages = {}

    def command(args, **kwargs):
        if args[0] == "dpkg-query":
            status = packages.get(args[-1])
            return subprocess.CompletedProcess(args, int(status is None), status or "", "")
        return subprocess.CompletedProcess(args, 0)

    run = Mock(side_effect=command)
    download = Mock(return_value=io.BytesIO(b"test package"))
    monkeypatch.setattr(haply.subprocess, "run", run)
    monkeypatch.setattr(haply, "urlopen", download)
    monkeypatch.setattr(
        haply.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "26.04"}
    )
    monkeypatch.setattr(haply.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(haply.os, "geteuid", lambda: 1000)
    return packages, run, download


def test_ubuntu26_reuses_installed_hub_without_downloading_or_installing(installation, capsys):
    packages, run, download = installation
    packages["haply-hub"] = "installed"
    haply.install()
    download.assert_not_called()
    assert all(call.args[0][0] == "dpkg-query" for call in run.call_args_list)
    assert "keep it open on the surgeon host" in capsys.readouterr().out


@pytest.mark.parametrize("status", [None, "config-files", "unpacked", "half-configured"])
def test_ubuntu26_requires_a_fully_installed_hub(installation, status):
    packages, run, download = installation
    packages["haply-hub"] = status
    with pytest.raises(ValueError, match="Ubuntu 26.04, install Haply Hub"):
        haply.install()
    download.assert_not_called()
    assert all(call.args[0][0] == "dpkg-query" for call in run.call_args_list)


def test_installed_pinned_service_needs_no_hub(installation):
    packages, run, download = installation
    packages["haply-inverse-service"] = f"{haply.VERSION} installed"
    haply.install()
    download.assert_not_called()
    assert run.call_count == 1


def test_native_host_without_hub_still_installs_standalone(installation, monkeypatch):
    _, run, download = installation
    monkeypatch.setattr(
        haply.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"}
    )
    haply.install()
    assert "ubuntu2404-amd64" in download.call_args.args[0]
    command = run.call_args.args[0]
    assert command[:5] == ["sudo", "apt-get", "install", "-y", "--no-remove"]
    assert Path(command[-1]).name == "haply-inverse-service-ubuntu2404-amd64-3.5.6.deb"


def test_docker_extraction_does_not_reuse_host_hub(installation, monkeypatch, tmp_path):
    packages, run, download = installation
    packages["haply-hub"] = "installed"
    monkeypatch.setattr(
        haply.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"}
    )
    download.side_effect = OSError("download unavailable")
    with pytest.raises(OSError, match="download unavailable"):
        haply.install(extract=tmp_path / "haply")
    download.assert_called_once()
    run.assert_not_called()
