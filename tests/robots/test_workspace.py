# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Workspace geometry, bounded model paths and asynchronous lifecycle checks."""

import threading

import numpy as np
import pytest
from telesurgery_robots.workspace import SerialModel, Workspace, axis_bounds


def chain(q):
    """Independent standard DH chain with seven revolute joints and a fixed tool."""
    transform = np.eye(4)
    axes, origins = [], []
    for theta, a, d, alpha in zip(
        q,
        [0, 0, 0.08, -0.08, 0, 0.09, 0],
        [0.33, 0, 0.32, 0, 0.38, 0, 0.11],
        [-np.pi / 2, np.pi / 2, np.pi / 2, -np.pi / 2, np.pi / 2, np.pi / 2, 0],
        strict=True,
    ):
        origins.append(transform[:3, 3].copy())
        axes.append(transform[:3, 2].copy())
        c, s, ca, sa = np.cos(theta), np.sin(theta), np.cos(alpha), np.sin(alpha)
        transform = transform @ np.array(
            [
                [c, -s * ca, s * sa, a * c],
                [s, c * ca, -c * sa, a * s],
                [0, sa, ca, d],
                [0, 0, 0, 1],
            ]
        )
    jacobian = np.array(
        [
            np.r_[np.cross(axis, transform[:3, 3] - origin), axis]
            for axis, origin in zip(axes, origins, strict=True)
        ]
    ).T
    return transform, jacobian


def test_serial_model_matches_independent_fk_and_jacobian_away_from_reference():
    rng = np.random.default_rng(42)
    for _ in range(10):
        reference = rng.uniform(-2, 2, 7)
        pose, jacobian = chain(reference)
        model = SerialModel(reference, pose[:3, 3], pose[:3, :3], jacobian)
        for _ in range(10):
            q = rng.uniform(-2, 2, 7)
            actual, expected = model(q), chain(q)
            for a, b in zip(actual, expected, strict=True):
                np.testing.assert_allclose(a, b, atol=1e-12)


def test_axis_extents_use_continuous_ik_paths_within_joint_limits():
    reference = np.array([0.2, -0.4, 0.3, -1.8, 0.2, 1.5, -0.3])
    limits = np.tile([-2.8, 2.8], (7, 1))
    visited = []

    def model(q):
        assert np.all(q >= limits[:, 0]) and np.all(q <= limits[:, 1])
        visited.append(q.copy())
        return chain(q)

    bounds = axis_bounds(model, reference, limits, threading.Event())
    origin = chain(reference)[0][:3, 3]
    assert np.all(np.asarray(bounds["min"]) < origin - 0.005)
    assert np.all(np.asarray(bounds["max"]) > origin + 0.005)
    assert len(visited) > 100


def test_workspace_refresh_is_nonblocking_and_old_job_cannot_publish_after_close():
    cache = Workspace()
    entered, finish = threading.Event(), threading.Event()

    def calculate(cancelled):
        entered.set()
        assert finish.wait(2)
        return {"min": [-1] * 3, "max": [1] * 3}

    assert cache.update([0] * 3, np.eye(3), calculate, idle=False) is None
    assert cache.job is None  # No new calculation during motion.
    assert cache.update([0] * 3, np.eye(3), calculate, idle=True) is None
    assert entered.wait(2)
    cache.close()
    finish.set()
    cache.job.join(2)
    assert cache.result is None
    cache.update([0] * 3, np.eye(3), calculate, idle=True)
    cache.job.join(2)
    assert cache.result["unit"] == "m"
    old = cache.result
    assert cache.update([0.1, 0, 0], np.eye(3), calculate, idle=False) is old
    cache.update([2, 0, 0], np.eye(3), calculate, idle=True)
    cache.job.join(2)
    assert cache.reference[0] == 2


def test_workspace_cancellation_and_joint_limit_errors():
    event = threading.Event()
    event.set()
    with pytest.raises(ValueError, match="cancelled"):
        axis_bounds(chain, np.zeros(7), np.tile([-2, 2], (7, 1)), event)
    with pytest.raises(ValueError, match="joint limit"):
        axis_bounds(chain, np.ones(7) * 2, np.tile([-2, 2], (7, 1)), threading.Event())


def test_physical_mira_extent_queries_never_send_motion(monkeypatch):
    from telesurgery_robots.mira.workspace import vendor_bounds

    requests = []
    closed = []
    poses = {"left": [0, 0, 0, 30], "right": [0, 0, 0, 30]}
    joints = {arm: [0, 60, 70, 80, 0, 0] for arm in poses}

    class Vendor:
        def __init__(self, uri, **kwargs):
            pass

        def send(self, request):
            assert request["method"] == "get_mira_cartesian_ik"
            requests.append(request["method"])
            result = {arm: list(q) for arm, q in joints.items()}
            # A fixture with finite travel and a discontinuous branch outside it.
            position = request["params"]["left"][:3]
            result["left"][0] = 100 if max(abs(v) for v in position) > 20 else position[0]
            return result

        def close(self):
            closed.append(True)

    monkeypatch.setattr("telesurgery_robots.mira.workspace.RpcClient", Vendor)
    bounds = vendor_bounds("fixture", "left", poses, joints, threading.Event())
    assert bounds == {"min": [-0.02] * 3, "max": [0.02] * 3}
    assert len(requests) > 60 and closed == [True]
    assert poses["left"] == [0, 0, 0, 30]  # The live feedback snapshot is untouched.
