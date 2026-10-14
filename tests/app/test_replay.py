# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replay admission, independent owners and cancellation use the normal control lease."""

import gzip
import json

import pytest
from telesurgery.controller.replay import Catalog, Playback, Rendezvous, check_initial
from telesurgery_core.control.access import Ownership


@pytest.fixture
def catalog(tmp_path):
    directory = tmp_path / "versius/keyboard"
    directory.mkdir(parents=True)
    for role in ("left", "right"):
        with gzip.open(directory / f"{role}.jsonl.gz", "wt") as output:
            output.write(json.dumps({"t": 0, "keys": [], "speeds": [20, 50, 40]}))
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "environment": "versius",
                "device": "keyboard",
                "task": "Handoff",
                "replay_verified": True,
                "streams": {role: {"file": f"{role}.jsonl.gz"} for role in ("left", "right")},
            }
        )
    )
    return Catalog(tmp_path)


def robot(role="left", kind="versius-sim"):
    return {"id": f"node:{role}", "kind": kind, "simulation": kind.endswith("-sim")}


@pytest.mark.parametrize("component", ["joints_deg", "grippers"])
def test_mira_replay_requires_both_arms_and_explains_scene_reset(component):
    path, manifest, role = Catalog().get("mira/keyboard", robot("mira", "mira-sim"))
    initial = manifest["streams"][role]["initial"]
    state = json.loads(json.dumps(initial))
    if component == "joints_deg":
        state[component]["right"][4] = -25.6
    else:
        state[component]["right"] = 0.5
    with pytest.raises(ValueError, match=r"\(right\); use Reset scene before replay"):
        check_initial(state, initial, starting_scene=manifest["starting_scene"])
    check_initial(initial, initial, starting_scene=manifest["starting_scene"])


def test_catalog_requires_verified_recording_and_matching_simulation(catalog):
    assert len(catalog.list()) == 1
    with pytest.raises(ValueError, match="matching simulation"):
        catalog.get("versius/keyboard", robot(kind="versius"))
    with pytest.raises(ValueError, match="this arm"):
        catalog.get("versius/keyboard", robot("assistant"))
    path, manifest = catalog.recordings["versius/keyboard"]
    manifest["replay_verified"] = False
    path.write_text(json.dumps(manifest))
    assert not Catalog(path.parents[2]).list()


def test_two_surgeons_start_together_and_wait_for_both_to_finish(catalog):
    now = [10.0]

    def clock():
        return now[0]

    barrier = Rendezvous(catalog, clock)
    owners = {f"node:{role}": Ownership(clock) for role in ("left", "right")}
    tokens = {
        role: owners[f"node:{role}"].acquire(peer) for role, peer in [("left", "X"), ("right", "Y")]
    }
    run = barrier.join("versius/keyboard", robot(), "X", tokens["left"])
    assert barrier.poll(run, "X", "node:left", owners)["elapsed"] is None
    assert barrier.join("versius/keyboard", robot("right"), "Y", tokens["right"]) == run
    assert barrier.poll(run, "Y", "node:right", owners)["elapsed"] == -1
    assert not barrier.poll(run, "X", "node:left", owners, finished=True)["done"]
    assert barrier.poll(run, "Y", "node:right", owners, finished=True)["done"]


@pytest.mark.parametrize("failure", ["cancel", "release", "silent"])
def test_one_participant_stopping_cancels_the_other(catalog, failure):
    now = [10.0]
    barrier = Rendezvous(catalog, lambda: now[0])
    owners = {f"node:{role}": Ownership(lambda: now[0]) for role in ("left", "right")}
    run = None
    for role, peer in [("left", "X"), ("right", "Y")]:
        run = barrier.join(
            "versius/keyboard", robot(role), peer, owners[f"node:{role}"].acquire(peer)
        )
    with pytest.raises(PermissionError):
        barrier.cancel(run, "Y", "node:left")
    if failure == "cancel":
        barrier.cancel(run, "X", "node:left")
    elif failure == "release":
        owners["node:left"].release()
    else:
        now[0] += 0.51
    with pytest.raises(RuntimeError, match="Replay stopped"):
        barrier.poll(run, "Y", "node:right", owners)


def test_same_surgeon_cannot_prepare_both_versius_arms(catalog):
    barrier = Rendezvous(catalog)
    barrier.join("versius/keyboard", robot(), "X", "left-token")
    with pytest.raises(PermissionError, match="separate surgeon"):
        barrier.join("versius/keyboard", robot("right"), "X", "right-token")


def test_delayed_dashboard_discards_replay_instead_of_catching_up():
    now = [1.0]
    instance = Playback(
        {"kind": "franka-sim", "controls": {"cartesian": {"linear_speed_m_s": 0.1}}},
        {"device": "keyboard"},
        "franka",
        [{"t": 0, "keys": ["w"], "speeds": [20, 50, 40]}],
        "run",
        lambda: now[0],
    )
    now[0] += 0.31
    with pytest.raises(TimeoutError, match="stopped polling"):
        instance.read(0, {})
    assert instance.index == 0


def test_playback_preserves_each_button_edge_when_two_samples_are_due():
    instance = Playback(
        {"kind": "franka-sim", "controls": {"cartesian": {"linear_speed_m_s": 0.1}}},
        {"device": "keyboard"},
        "franka",
        [
            {"t": 0, "keys": [], "speeds": [20, 50, 40]},
            {"t": 0.05, "keys": ["w"], "speeds": [20, 50, 40]},
            {"t": 0.10, "keys": [], "speeds": [20, 50, 40]},
        ],
        "run",
    )
    instance.read(0, {})
    movement = instance.read(0.11, {})
    assert movement["request"][0] == "jog"
    assert not movement["done"]
    assert instance.read(0.12, {})["request"] == ("release", {})


def test_handoff_barrier_tracks_each_owner_and_survives_motion_acknowledgements(catalog):
    path, manifest = catalog.recordings["versius/keyboard"]
    manifest["barriers"] = 2
    barrier = Rendezvous(catalog)
    owners = {f"node:{role}": Ownership() for role in ("left", "right")}
    for role, peer in (("left", "X"), ("right", "Y")):
        run = barrier.join(
            "versius/keyboard", robot(role), peer, owners[f"node:{role}"].acquire(peer)
        )
    assert barrier.poll(run, "X", "node:left", owners, checkpoint=1)["checkpoint"] == 0
    assert barrier.poll(run, "Y", "node:right", owners, checkpoint=1)["checkpoint"] == 1
    # A normal robot.move also polls the barrier, without declaring a new stage.
    assert barrier.poll(run, "X", "node:left", owners)["checkpoint"] == 1
    assert barrier.poll(run, "Y", "node:right", owners, checkpoint=2)["checkpoint"] == 1
    with pytest.raises(ValueError, match="checkpoint"):
        barrier.poll(run, "X", "node:left", owners, checkpoint=0)
    with pytest.raises(PermissionError):
        barrier.poll(run, "X", "node:right", owners, checkpoint=2)
    assert barrier.poll(run, "X", "node:left", owners, checkpoint=2)["checkpoint"] == 2


@pytest.mark.parametrize("first", ["left", "right"])
def test_checkpoint_replay_starts_alone_and_waits_at_handoff_for_late_surgeon(catalog, first):
    _, manifest = catalog.recordings["versius/keyboard"]
    manifest.update(version=2, barriers=3)
    now = [10.0]

    def clock():
        return now[0]

    barrier = Rendezvous(catalog, clock)
    second = "right" if first == "left" else "left"
    owners = {f"node:{first}": Ownership(clock)}
    first_owner = owners[f"node:{first}"]
    token = first_owner.acquire("X")
    run = barrier.join("versius/keyboard", robot(first), "X", token)
    assert barrier.poll(run, "X", f"node:{first}", owners)["elapsed"] == 0
    # The other surgeon need not even own its arm yet. Keep the first live
    # well beyond motion deadlines while it holds at the first handoff.
    for _ in range(600):
        now[0] += 0.1
        first_owner.validate("X", token)
        result = barrier.poll(run, "X", f"node:{first}", owners, checkpoint=1)
        assert result["checkpoint"] == 0 and not result["done"]
    with pytest.raises(RuntimeError, match="already ready"):
        barrier.join("versius/keyboard", robot(first), "X", token)
    with pytest.raises(PermissionError, match="separate surgeon"):
        barrier.join("versius/keyboard", robot(second), "X", "another-token")
    owners[f"node:{second}"] = second_owner = Ownership(clock)
    second_token = second_owner.acquire("Y")
    assert barrier.join("versius/keyboard", robot(second), "Y", second_token) == run
    result = barrier.poll(run, "Y", f"node:{second}", owners, checkpoint=1)
    assert result["elapsed"] == pytest.approx(60)
    assert result["checkpoint"] == 1 and not result["done"]
    for checkpoint in (2, 3):
        result = barrier.poll(run, "Y", f"node:{second}", owners, checkpoint=checkpoint)
        assert result["checkpoint"] == checkpoint - 1
        result = barrier.poll(run, "X", f"node:{first}", owners, checkpoint=checkpoint)
        assert result["checkpoint"] == checkpoint
    assert not barrier.poll(run, "X", f"node:{first}", owners, finished=True)["done"]
    assert barrier.poll(run, "Y", f"node:{second}", owners, finished=True)["done"]


@pytest.mark.parametrize("failure", ["cancel", "release", "silent", "reacquire"])
def test_independent_replay_cannot_continue_after_first_participant_stops(catalog, failure):
    _, manifest = catalog.recordings["versius/keyboard"]
    manifest.update(version=2, barriers=3)
    now = [10.0]

    def clock():
        return now[0]

    barrier = Rendezvous(catalog, clock)
    owners = {"node:left": Ownership(clock), "node:right": Ownership(clock)}
    left_token = owners["node:left"].acquire("X")
    run = barrier.join("versius/keyboard", robot(), "X", left_token)
    barrier.poll(run, "X", "node:left", owners, checkpoint=1)
    right_token = owners["node:right"].acquire("Y")
    assert barrier.join("versius/keyboard", robot("right"), "Y", right_token) == run
    if failure == "cancel":
        barrier.cancel(run, "X", "node:left")
    elif failure in {"release", "reacquire"}:
        owners["node:left"].release()
        if failure == "reacquire":
            assert owners["node:left"].acquire("X") != left_token
    else:
        now[0] += 0.51
    with pytest.raises(RuntimeError, match="Replay stopped"):
        barrier.poll(run, "Y", "node:right", owners, checkpoint=1)


@pytest.mark.parametrize("left_device", ["keyboard", "gamepad", "haply"])
@pytest.mark.parametrize("right_device", ["keyboard", "gamepad", "haply"])
def test_handoff_joins_across_device_recordings(left_device, right_device):
    barrier = Rendezvous(Catalog())
    owners = {f"node:{role}": Ownership() for role in ("left", "right")}
    left = barrier.join(f"versius/{left_device}", robot(), "X", owners["node:left"].acquire("X"))
    assert barrier.poll(left, "X", "node:left", owners, checkpoint=1)["checkpoint"] == 0
    right = barrier.join(
        f"versius/{right_device}", robot("right"), "Y", owners["node:right"].acquire("Y")
    )
    assert left == right
    assert barrier.poll(right, "Y", "node:right", owners, checkpoint=1)["checkpoint"] == 1
    for checkpoint in (2, 3):
        assert (
            barrier.poll(left, "X", "node:left", owners, checkpoint=checkpoint)["checkpoint"]
            == checkpoint - 1
        )
        assert (
            barrier.poll(right, "Y", "node:right", owners, checkpoint=checkpoint)["checkpoint"]
            == checkpoint
        )
    # A mixed-device participant retains the same Stop/ownership semantics.
    barrier.cancel(right, "Y", "node:right")
    with pytest.raises(RuntimeError, match="Replay stopped"):
        barrier.poll(left, "X", "node:left", owners)


@pytest.mark.parametrize("difference", ["node", "task", "version"])
def test_handoff_does_not_join_other_scene_task_or_legacy_recording(difference):
    import copy

    catalog = Catalog()
    _, manifest = catalog.recordings["versius/keyboard"]
    alternate = copy.deepcopy(manifest)
    if difference == "task":
        alternate["handoff_group"] = "another-task"
    elif difference == "version":
        alternate["version"] = 1
    catalog.recordings["versius/keyboard"] = catalog.recordings["versius/keyboard"][0], alternate
    barrier = Rendezvous(catalog)
    left = barrier.join("versius/gamepad", robot(), "X", "left-token")
    other_robot = robot("right")
    if difference == "node":
        other_robot["id"] = "another-node:right"
    right = barrier.join("versius/keyboard", other_robot, "Y", "right-token")
    assert right != left


@pytest.mark.parametrize("field,value", [("barriers", 2), ("streams", {"right": {}})])
def test_handoff_rejects_incompatible_group_definition(field, value):
    catalog = Catalog()
    barrier = Rendezvous(catalog)
    barrier.join("versius/gamepad", robot(), "X", "left-token")
    catalog.recordings["versius/keyboard"][1][field] = value
    with pytest.raises(ValueError, match="incompatible handoff"):
        barrier.join("versius/keyboard", robot("right"), "Y", "right-token")
