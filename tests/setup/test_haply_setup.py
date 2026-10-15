# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Reuse the Hub on newer hosts without omitting the service from Docker images."""

import hashlib
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
        if args[0] == "dpkg-deb":
            root = Path(args[-1])
            (root / "usr/bin").mkdir(parents=True)
            (root / "usr/bin/haply-inverse-service").write_bytes(b"test binary")
            docs = root / "usr/share/doc/haply-inverse-service"
            docs.mkdir(parents=True)
            (docs / "copyright").write_text("test license")
        return subprocess.CompletedProcess(args, 0)

    run = Mock(side_effect=command)
    download = Mock(return_value=io.BytesIO(b"test package"))
    monkeypatch.setattr(haply.subprocess, "run", run)
    monkeypatch.setattr(haply, "urlopen", download)
    monkeypatch.setattr(
        haply, "DIGESTS", dict.fromkeys(haply.DIGESTS, hashlib.sha256(b"test package").hexdigest())
    )
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


@pytest.mark.parametrize("release", ["22.04", "24.04"])
@pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
@pytest.mark.parametrize("extract", [False, True])
def test_verified_package_is_installed_or_extracted(
    installation, monkeypatch, tmp_path, release, machine, extract
):
    _, run, download = installation
    system = {"ID": "ubuntu", "VERSION_ID": release}
    monkeypatch.setattr(haply.platform, "freedesktop_os_release", lambda: system)
    monkeypatch.setattr(haply.platform, "machine", lambda: machine)
    destination = tmp_path / "haply" if extract else None
    haply.install(extract=destination)
    download.assert_called_once_with(
        f"{haply.CDN}/{haply.package_name(system, machine)}", timeout=60
    )
    if extract:
        assert (destination / "haply-inverse-service").read_bytes() == b"test binary"
        assert (destination / "doc/copyright").read_text() == "test license"
        assert all(call.args[0][0] in {"dpkg-deb", "strip"} for call in run.call_args_list)
    else:
        assert run.call_args.args[0][:5] == ["sudo", "apt-get", "install", "-y", "--no-remove"]


@pytest.mark.parametrize("extract", [False, True])
@pytest.mark.parametrize("unknown", [False, True])
def test_unverified_package_never_reaches_installation_or_extraction(
    installation, monkeypatch, tmp_path, extract, unknown
):
    _, run, download = installation
    monkeypatch.setattr(
        haply.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"}
    )
    if unknown:
        monkeypatch.setattr(haply, "DIGESTS", {})
    else:
        download.return_value = io.BytesIO(b"changed package")
    with pytest.raises(
        ValueError, match="Unrecognized Haply package|Haply package digest mismatch"
    ):
        haply.install(extract=tmp_path / "haply" if extract else None)
    assert download.call_count == (0 if unknown else 1)
    assert all(call.args[0][0] == "dpkg-query" for call in run.call_args_list)
