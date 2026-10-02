# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Clock provisioning is persistent, idempotent, and part of the normal setup entrypoint."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("clock_setup", ROOT / "scripts/clock_sync.py")
clock_setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clock_setup)


def test_existing_chrony_needs_no_elevation_or_changes(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert args == ["systemctl", "is-active", "--quiet", "chrony"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(clock_setup.subprocess, "run", run)
    monkeypatch.setattr(clock_setup.sys, "argv", ["clock_sync.py"])
    clock_setup.main()
    assert len(calls) == 1


def test_configuration_enables_system_service_without_clock_steps(tmp_path, monkeypatch):
    target = tmp_path / "chrony.conf"
    target.write_text("pool previous.example.org\n")
    calls = []

    def run(args, **kwargs):
        calls.append(list(args))
        return SimpleNamespace(returncode=3 if "is-active" in args else 0)

    monkeypatch.setattr(clock_setup, "Path", lambda path: target)
    monkeypatch.setattr(clock_setup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(clock_setup.shutil, "which", lambda name: "/usr/sbin/chronyd")
    monkeypatch.setattr(clock_setup.subprocess, "run", run)
    monkeypatch.setattr(clock_setup.sys, "argv", ["clock_sync.py", "--client", "192.0.2.1"])
    clock_setup.main()
    assert ["systemctl", "enable", "chrony.service"] in calls
    assert ["systemctl", "restart", "chrony.service"] in calls
    assert "server 192.0.2.1 iburst xleave" in target.read_text()
    assert "makestep" not in target.read_text()
    assert (
        target.with_suffix(".conf.before-telesurgery").read_text() == "pool previous.example.org\n"
    )
