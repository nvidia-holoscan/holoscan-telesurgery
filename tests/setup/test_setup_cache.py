# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A fast setup must rebuild after input changes, damage, or an interrupted build."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "setup_cache", Path(__file__).resolve().parents[2] / "scripts/setup_cache.py"
)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


def write(root, name, contents="original"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    write(root, "setup.sh")
    write(root, "uv.lock")
    write(root, "native/driver.cpp")
    write(root, "packages/app/pyproject.toml")
    write(root, "scripts/builders/sdk5.py")
    write(root, ".venv-sdk5/bin/python")
    write(root, ".venv-sdk5/lib/python3.12/site-packages/codec.so")
    write(root, "workspace/sim-deps/zmq/__init__.py")
    for sdk in (4, 5):
        write(root, f"dependencies/sdk{sdk}.toml", '[holoscan]\nprovider="installed"\n')
    monkeypatch.setattr(cache.subprocess, "check_output", lambda *a, **kw: "GPU-1, RTX, 590\n")
    args = (root, "5", root / "workspace", False, root / "pending")
    assert not cache.check(*args)
    cache.record(*args)
    assert cache.check(*args)
    return args


@pytest.mark.parametrize(
    "changed",
    [
        "uv.lock",
        "setup.sh",
        "native/driver.cpp",
        "packages/app/pyproject.toml",
        "scripts/builders/sdk5.py",
        ".venv-sdk5/lib/python3.12/site-packages/codec.so",
        "workspace/sim-deps/zmq/__init__.py",
    ],
)
def test_inputs_and_installed_files_invalidate_success(installation, changed):
    write(installation[0], changed, "changed")
    assert not cache.check(*installation)


def test_deleted_codec_and_interrupted_rebuild_cannot_reuse_old_success(installation):
    root, sdk, workspace, franka, _ = installation
    binding = root / ".venv-sdk5/lib/python3.12/site-packages/codec.so"
    binding.unlink()
    assert not cache.check(*installation)
    assert not cache.stamp_path(root, sdk, workspace, franka).exists()
    # Restoring a missing file without completing validation must not revive the stamp.
    write(root, binding.relative_to(root))
    assert not cache.check(*installation)
    cache.record(*installation)
    assert cache.check(*installation)


def test_regular_imports_and_ui_edits_do_not_require_a_rebuild(installation):
    root = installation[0]
    write(root, ".venv-sdk5/lib/python3.12/site-packages/__pycache__/module.pyc")
    write(root, "scripts/builders/__pycache__/sdk5.pyc")
    write(root, "packages/app/src/telesurgery/server/static/robots.js")
    assert cache.check(*installation)


@pytest.mark.parametrize("change", ["sdk", "workspace", "profile", "flags", "gpu"])
def test_cache_is_specific_to_build_options_and_hardware(installation, monkeypatch, change):
    root, sdk, workspace, franka, pending = installation
    if change == "sdk":
        sdk = "4"
    elif change == "workspace":
        workspace = root / "another-workspace"
    elif change == "profile":
        franka = True
    elif change == "flags":
        monkeypatch.setenv("CUDAARCHS", "120")
    else:
        monkeypatch.setattr(cache.subprocess, "check_output", lambda *a, **kw: "GPU-2, RTX, 591\n")
    assert not cache.check(root, sdk, workspace, franka, pending)


def test_force_invalidates_success_before_work_begins(installation):
    assert not cache.check(*installation, force=True)
    assert not cache.check(*installation)
    cache.record(*installation)
    assert cache.check(*installation)


def test_edits_during_setup_are_not_marked_validated(installation):
    assert not cache.check(*installation, force=True)
    write(installation[0], "uv.lock", "changed while building")
    cache.record(*installation)
    assert not cache.check(*installation)


@pytest.mark.parametrize("contents", ["incomplete JSON", "[]"])
def test_corrupt_cache_is_replaced_after_success(installation, contents):
    root, sdk, workspace, franka, _ = installation
    cache.stamp_path(root, sdk, workspace, franka).write_text(contents)
    assert not cache.check(*installation)
    cache.record(*installation)
    assert cache.check(*installation)


def test_external_symlink_targets_are_checked(installation, tmp_path):
    root = installation[0]
    external = write(tmp_path, "external/tensorrt/binding.so")
    (root / ".venv-sdk5/lib/tensorrt").symlink_to(external.parent, target_is_directory=True)
    assert not cache.check(*installation)
    cache.record(*installation)
    assert cache.check(*installation)
    external.unlink()
    assert not cache.check(*installation)
