# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Dependency changes must not reuse the wrong source or touch installed providers."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "dependency_setup", Path(__file__).resolve().parents[2] / "scripts/builders/dependencies.py"
)
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def test_pinned_sources_survive_url_changes_and_interrupted_fetches(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-q")
    (upstream / "value").write_text("first\n")
    git(upstream, "add", ".")
    git(
        upstream,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "first",
    )
    first = git(upstream, "rev-parse", "HEAD")
    (upstream / "value").write_text("second\n")
    git(
        upstream,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qam",
        "second",
    )
    source = {"git": upstream.as_uri(), "rev": first}
    target = deps.checkout("sdk", source, tmp_path / "build")
    assert (target / "value").read_text() == "first\n"
    assert deps.checkout("sdk", source, tmp_path / "build") == target
    replacement = deps.checkout("sdk", {**source, "git": str(upstream)}, tmp_path / "build")
    assert replacement != target
    assert git(upstream, "show", "HEAD:value") == "second"
    # Recover after a process exits between fetch and checkout.
    git(target, "symbolic-ref", "HEAD", "refs/heads/unborn")
    assert deps.checkout("sdk", source, tmp_path / "build") == target
    assert git(target, "rev-parse", "HEAD") == first


def test_installed_provider_does_not_install(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("installed provider ran a package manager")

    monkeypatch.setattr(deps, "run", forbidden)
    deps.install({"provider": "installed"})


def test_package_provider_only_installs_missing_apt_packages(monkeypatch):
    commands = []
    monkeypatch.setattr(deps, "run", lambda *args: commands.append(args))
    monkeypatch.setattr(deps.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        deps.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "installed 1.2.0", ""),
    )
    deps.install(
        {"provider": "packages", "apt": ["sdk=1.2.0", "camera=2.0"], "pip": ["sdk==1.2.0"]}
    )
    assert commands[0] == ("apt-get", "update")
    assert commands[1] == (
        "apt-get",
        "install",
        "-y",
        "--no-remove",
        "--no-install-recommends",
        "camera=2.0",
    )
    assert commands[2][-1] == "sdk==1.2.0"


def test_invalid_provider_fails_before_install(tmp_path):
    config = tmp_path / "dependencies.toml"
    config.write_text('[holoscan]\nprovider="packagez"\n[hololink]\nprovider="installed"\n')
    with pytest.raises(ValueError, match="provider must be"):
        deps.load(config)
