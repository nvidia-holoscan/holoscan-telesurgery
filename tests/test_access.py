# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Admission and robot ownership invariants are independent of model and SDK."""

import pytest
from telesurgery_core.control.access import Access, Ownership


def test_names_do_not_confer_access_and_robot_permission_requires_request():
    access = Access()
    access.request("first", "Dr Example", True)
    access.request("second", "Dr Example")
    with pytest.raises(PermissionError):
        access.require("first")
    access.approve("first", True)
    access.approve("second", True)
    assert access.require("first", robot=True).robot
    with pytest.raises(PermissionError):
        access.require("second", robot=True)
    access.revoke("first")
    with pytest.raises(PermissionError):
        access.require("first")
    with pytest.raises(ValueError):
        access.approve("first", True)


def test_ownership_never_replays_old_tokens_or_sequences():
    now = [10.0]
    owner = Ownership(clock=lambda: now[0])
    token = owner.acquire("one")
    with pytest.raises(PermissionError):
        owner.acquire("two")
    owner.validate("one", token, 1)
    with pytest.raises(ValueError, match="Stale"):
        owner.validate("one", token, 1)
    now[0] += 3
    assert owner.expired()
    with pytest.raises(PermissionError):
        owner.validate("one", token, 2)
    owner.release()
    next_token = owner.acquire("two")
    assert next_token != token
    with pytest.raises(PermissionError):
        owner.validate("one", token, 3)
    owner.validate("two", next_token, 1)
    owner.release()
    owner.ready = False
    with pytest.raises(RuntimeError):
        owner.acquire("one")


def test_approval_survives_restart_but_never_follows_a_display_name(tmp_path):
    import secrets

    from telesurgery_core.configuration import load

    path = tmp_path / "surgeons.yaml"
    identity, stranger = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    access = Access(path)
    access.request("first", "Dr Example", False, identity)
    access.approve("first")
    access.disconnect("first")
    access = Access(path)
    assert access.list()[0]["status"] == "offline"
    offline = access.list()[0]["id"]
    assert access.request("second", "Dr Example", False, stranger)["status"] == "pending"
    assert access.request("returning", "Dr Example", False, identity)["status"] == "approved"
    assert identity not in path.read_text()
    with pytest.raises(ValueError, match="already connected"):
        access.request("duplicate", "Other name", False, identity)
    # A stale offline row must revoke the now-connected owner of that identity too.
    assert access.revoke(offline) == ["returning"]
    with pytest.raises(PermissionError):
        access.require("returning")
    assert load(path) == {}
    access.disconnect("returning")
    assert access.request("next", "Dr Example", True, identity)["status"] == "pending"
    access.approve("next", False)
    access.disconnect("next")
    access = Access(path)
    assert access.request("escalation", "Dr Example", True, identity)["status"] == "pending"
