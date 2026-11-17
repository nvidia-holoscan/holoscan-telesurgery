# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A controlling surgeon's priority area reaches the camera's encoder; everyone sees it."""

import asyncio
import contextlib
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import pytest_asyncio
from telesurgery.nodes import local
from telesurgery.server.application import Application
from telesurgery_core.transport.protocol import VideoHeader
from telesurgery_core.video import region
from telesurgery_core.video.config import Config
from telesurgery_core.video.model import Frame
from telesurgery_runtime.application import video

BOX = [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
LASSO = [[0.1, 0.2], [0.5, 0.1], [0.9, 0.3], [0.7, 0.8], [0.3, 0.9]]
FRAME = Frame(VideoHeader(0, 0, 64, 48), None)
STATE = ("region_supported", "region_unavailable", "region", "region_by")


class Encoder:
    """Stands in for the GPU encoder: records the areas the camera worker hands it."""

    created = []
    capable = {"h264", "h265"}
    refuse = ""

    def __init__(self, config, *, encode):
        self.config, self.areas, self.closed = config, [], False
        # Like NVENC: no area with a format or adaptive quantization that excludes one.
        self.supports_region = config.codec in self.capable and not region.unavailable(
            config.codec, config.encoder_extra
        )
        Encoder.created.append(self)

    def set_region(self, mask):
        if mask is not None and Encoder.refuse:
            raise RuntimeError(Encoder.refuse)
        self.areas.append(None if mask is None else mask.copy())

    def request_keyframe(self):
        pass

    def encode(self, frame):
        return frame.header, b"frame"

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def encoder(monkeypatch):
    monkeypatch.setattr(video, "CodecWorker", Encoder)
    monkeypatch.setattr(Encoder, "created", [])
    monkeypatch.setattr(Encoder, "capable", {"h264", "h265"})
    monkeypatch.setattr(Encoder, "refuse", "")
    return Encoder


def settings_file(tmp_path, **camera):
    path = tmp_path / "camera.json"
    path.write_text(json.dumps({"camera": {"codec": "h264", **camera}}))
    return path


def status(path):
    return region.read_status(path.with_suffix(region.STATUS_SUFFIX))


async def swap_encoder(stage, path, codec):
    """Change the stream's codec as the node does, and wait for the worker's new encoder."""
    before = stage.codec
    path.write_text(json.dumps({"camera": {"codec": codec}}))
    stage.check_at = 0
    async with asyncio.timeout(5):
        while stage.codec is before:
            stage.compute(FRAME)
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_worker_applies_an_area_when_it_changes_and_again_on_a_new_encoder(tmp_path):
    path = settings_file(tmp_path)
    stage = video.Encode(Config(codec="h264"), path)
    stage.start()
    try:
        first = stage.codec
        assert stage.compute(FRAME) == (FRAME.header, b"frame")
        # A new encoder already has uniform quality: nothing to clear, but support is reported.
        assert first.areas == []
        assert status(path) == {"supported": True, "blocked": "", "revision": None, "error": ""}

        region.write_request(path.with_suffix(region.REQUEST_SUFFIX), 1, BOX)
        for _ in range(3):
            stage.compute(FRAME)
        assert len(first.areas) == 1  # only when it changes, not per frame
        mask = first.areas[0]
        assert mask.shape == (160, 285) and mask.dtype == np.uint8 and mask.flags.c_contiguous
        assert np.array_equal(mask, region.mask(BOX))
        assert status(path) == {"supported": True, "blocked": "", "revision": 1, "error": ""}

        # The latest area replaces the previous one from the next frame.
        region.write_request(path.with_suffix(region.REQUEST_SUFFIX), 2, LASSO)
        stage.compute(FRAME)
        assert len(first.areas) == 2 and np.array_equal(first.areas[1], region.mask(LASSO))
        assert status(path)["revision"] == 2

        # A codec change builds a new encoder; the area follows it without another request.
        await swap_encoder(stage, path, "h265")
        second = stage.codec
        assert first.closed and second is not first and second.config.codec == "h265"
        stage.compute(FRAME)
        assert len(second.areas) == 1 and np.array_equal(second.areas[0], region.mask(LASSO))
        assert status(path) == {"supported": True, "blocked": "", "revision": 2, "error": ""}

        region.write_request(path.with_suffix(region.REQUEST_SUFFIX), 3, None)
        stage.compute(FRAME)
        stage.compute(FRAME)
        assert second.areas[1:] == [None]
        assert status(path) == {"supported": True, "blocked": "", "revision": 3, "error": ""}
    finally:
        stage.stop()


@pytest.mark.asyncio
async def test_worker_keeps_streaming_when_the_encoder_cannot_or_will_not_take_an_area(
    tmp_path, encoder
):
    path = settings_file(tmp_path)
    stage = video.Encode(Config(codec="h264"), path)
    stage.start()
    try:
        encoder.refuse = "NVENC rejected the map"
        region.write_request(path.with_suffix(region.REQUEST_SUFFIX), 1, BOX)
        assert stage.compute(FRAME) == (FRAME.header, b"frame")
        assert status(path) == {
            "supported": True,
            "blocked": "",
            "revision": 1,
            "error": "NVENC rejected the map",
        }
        # The failed encoder is returned to uniform quality once, then left alone.
        assert stage.codec.areas == [None]
        assert stage.compute(FRAME) == (FRAME.header, b"frame")
        assert stage.codec.areas == [None]

        # An encoder without the capability is never asked.
        encoder.refuse = ""
        encoder.capable = {"h264"}
        await swap_encoder(stage, path, "nvjpeg")
        assert stage.compute(FRAME) == (FRAME.header, b"frame")
        assert stage.codec.areas == []
        assert status(path) == {
            "supported": False,
            "blocked": "it needs an H.264 or H.265 stream",
            "revision": 1,
            "error": "This encoder cannot use a priority area",
        }
    finally:
        stage.stop()


class Room:
    """One node with one camera; a real camera-worker stage runs against the fake encoder."""

    def __init__(self, tmp_path, monkeypatch):
        self.directory = tmp_path / "node"
        self.stage = self.pump = None
        create = asyncio.create_subprocess_exec

        async def worker(*args, **kwargs):
            return await create(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)

        monkeypatch.setattr(local.asyncio, "create_subprocess_exec", worker)
        self.node = self.new_node()

    def new_node(self):
        node = local.LocalNode(self.directory, None)
        node.region_capable = True
        node.cameras["scope"] = {
            "id": "scope",
            "name": "Endoscope",
            "source": "synthetic",
            "kind": "fixture",
            "width": 1280,
            "height": 720,
            "fps": 30,
            "modes": [{"width": 1280, "height": 720, "fps": [30, 60], "pixel_format": ""}],
            "codecs": ["h264", "h265", "nvjpeg"],
        }
        return node

    async def start(self, settings=None, frames=True):
        await self.node.start_camera("scope", settings)
        path = self.node.workers["scope"]["settings"]
        if self.stage is None or self.stage.settings_path != path or self.pump.done():
            await self.stop_frames()
            self.stage = video.Encode(Config(**json.loads(path.read_text())["camera"]), path)
            self.stage.start()
            self.pump = asyncio.create_task(self.frames(frames))

    async def frames(self, running):
        while running:
            self.stage.compute(FRAME)
            await asyncio.sleep(0.005)

    async def stop_frames(self):
        if self.pump:
            self.pump.cancel()
            await asyncio.gather(self.pump, return_exceptions=True)
            self.stage.stop()
            self.stage = self.pump = None

    def camera(self):
        return self.node.inventory()["cameras"][0]

    def area(self):
        return {key: self.camera()[key] for key in STATE}

    async def until(self, predicate):
        async with asyncio.timeout(5):
            while not predicate():
                await asyncio.sleep(0.01)

    async def close(self):
        await self.stop_frames()
        await self.node.close()


@pytest_asyncio.fixture
async def room(tmp_path, monkeypatch):
    room = Room(tmp_path, monkeypatch)
    yield room
    await room.close()


NONE = {"region_supported": True, "region_unavailable": "", "region": None, "region_by": ""}


@pytest.mark.asyncio
async def test_node_holds_the_area_for_the_session_and_reports_what_the_encoder_has(room):
    assert room.area() == NONE  # supported before the stream starts
    with pytest.raises(ValueError, match="Start the stream"):
        await room.node.set_region("scope", BOX, "Dr. Rivera")
    await room.start()
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    # Confirmed by the encoder before the call returns: a late joiner's inventory has it.
    assert room.area() == {**NONE, "region": BOX, "region_by": "Dr. Rivera"}
    assert np.array_equal(room.stage.codec.areas[-1], region.mask(BOX))

    await room.node.set_region("scope", LASSO, "Dr. Chen")  # the latest wins
    assert room.area() == {**NONE, "region": LASSO, "region_by": "Dr. Chen"}
    assert len(room.stage.codec.areas) == 2

    # Bitrate and codec changes keep it; the worker hands it to the new encoder.
    first = room.stage.codec
    await room.start({"bitrate_mbps": 8, "codec": "h265"})
    await room.until(lambda: room.stage.codec is not first)
    await room.until(lambda: room.stage.codec.areas)
    assert np.array_equal(room.stage.codec.areas[0], region.mask(LASSO))
    assert room.area() == {**NONE, "region": LASSO, "region_by": "Dr. Chen"}

    # So does stopping and restarting the stream, as a resolution change requires.
    await room.node.stop_camera("scope")
    assert room.area() == NONE
    await room.start({"width": 1280, "height": 720})
    await room.until(lambda: room.area()["region"])
    assert room.area() == {**NONE, "region": LASSO, "region_by": "Dr. Chen"}
    assert np.array_equal(room.stage.codec.areas[0], region.mask(LASSO))

    await room.node.set_region("scope", None)
    assert room.area() == NONE
    await room.until(lambda: room.stage.codec.areas[-1] is None)
    await room.node.set_region("scope", None)  # clearing nothing is not an error

    for bad in ([[0, 0], [1, 1]], [[0.5, 0.5], [0.51, 0.5], [0.51, 0.51]], "everything"):
        with pytest.raises(ValueError):
            await room.node.set_region("scope", bad, "Dr. Rivera")
    with pytest.raises(ValueError, match="Camera is unavailable"):
        await room.node.set_region("other", BOX)

    # It is never written to disk: a restarted node has uniform quality.
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    await room.close()
    room.node = room.new_node()
    assert room.area() == NONE
    assert "region" not in (room.directory / "streams.yaml").read_text()


@pytest.mark.asyncio
async def test_node_tells_no_support_apart_from_settings_that_prevent_an_area(room, encoder):
    # No region-capable encoder on this node: nothing to offer.
    room.node.region_capable = False
    await room.start()
    assert room.area() == {**NONE, "region_supported": False}
    with pytest.raises(ValueError, match="cannot use a priority area"):
        await room.node.set_region("scope", BOX)
    await room.node.set_region("scope", None)

    # Capable, but the stream's format cannot follow an area: say why.
    room.node.region_capable = True
    await room.start({"codec": "nvjpeg"})
    assert room.area() == {**NONE, "region_unavailable": "it needs an H.264 or H.265 stream"}
    with pytest.raises(ValueError, match="Priority area unavailable: it needs an H.264"):
        await room.node.set_region("scope", BOX)

    # The encoder's own adaptive quantization and an area exclude each other.
    await room.start({"codec": "h264", "encoder_extra": "aq=8"})
    quantization = (
        "turn off adaptive quantization (aq, temporalaq) in the stream's advanced settings"
    )
    assert room.area() == {**NONE, "region_unavailable": quantization}
    # The encoder built with it reports no support; that is the setting, not the node.
    await room.until(lambda: room.stage.codec.config.encoder_extra == "aq=8")
    await room.until(lambda: status(room.stage.settings_path)["blocked"] == quantization)
    assert not room.stage.codec.supports_region
    assert room.area() == {**NONE, "region_unavailable": quantization}
    with pytest.raises(ValueError, match="adaptive quantization"):
        await room.node.set_region("scope", BOX)
    # Removing it keeps the reason until the replacement encoder has taken over.
    await room.start({"encoder_extra": ""})
    assert room.area() == {**NONE, "region_unavailable": quantization}
    await room.until(lambda: not room.area()["region_unavailable"])
    assert room.stage.codec.config.encoder_extra == ""
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    for extra in ("aq=8", "temporalaq=on"):
        with pytest.raises(ValueError, match="Clear the priority area before"):
            await room.start({"encoder_extra": extra})
    assert room.camera()["encoder_extra"] == ""
    await room.start({"encoder_extra": "qmax=40"})  # other advanced settings are unaffected
    assert room.area()["region"] == BOX

    # A capture change is refused while streaming, and must not drop the area on the way.
    with pytest.raises(ValueError, match="Stop this stream"):
        await room.start({"codec": "nvjpeg", "fps": 60})
    assert room.area()["region"] == BOX
    # Moving to a format that cannot follow it clears it for good.
    await room.start({"codec": "nvjpeg"})
    assert room.area()["region"] is None
    await room.start({"codec": "h264"})
    await room.until(lambda: room.stage.codec.config.codec == "h264")
    assert room.area() == NONE

    # This camera's H.265 encoder turns out not to have the capability at all.
    encoder.capable = {"h264"}
    await room.start({"codec": "h265"})
    await room.until(lambda: room.stage.codec.config.codec == "h265")
    await room.until(lambda: not room.area()["region_supported"])
    assert room.area() == {**NONE, "region_supported": False}


@pytest.mark.asyncio
async def test_encoder_refusal_returns_to_uniform_quality_and_says_so(room, encoder):
    await room.start()
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    encoder.refuse = "NVENC rejected the map"
    with pytest.raises(RuntimeError, match="could not apply the priority area: NVENC rejected"):
        await room.node.set_region("scope", LASSO, "Dr. Chen")
    assert room.area() == {
        **NONE,
        "region_unavailable": "the encoder could not apply it; restart the stream to try again",
    }
    await room.until(lambda: room.stage.codec.areas[-1] is None)
    assert room.stage.compute(FRAME) == (FRAME.header, b"frame")
    with pytest.raises(ValueError, match="restart the stream"):
        await room.node.set_region("scope", BOX)
    # A restarted stream has a new encoder and may try again.
    encoder.refuse = ""
    await room.node.stop_camera("scope")
    await room.start()
    assert room.area() == NONE
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    assert room.area()["region"] == BOX

    # The same refusal while a new encoder takes over an existing area.
    encoder.refuse = "NVENC rejected the map"
    first = room.stage.codec
    await room.start({"codec": "h265"})
    await room.until(lambda: room.stage.codec is not first)
    await room.until(lambda: room.area()["region_unavailable"])
    assert room.area()["region"] is None and "scope" not in room.node.regions


@pytest.mark.asyncio
async def test_a_status_poll_during_a_refused_change_does_not_bring_back_the_old_area(
    room, encoder
):
    await room.start()
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    encoder.refuse = "NVENC rejected the map"

    async def poll():
        # Dashboards ask for status while the change is still waiting for the encoder.
        while True:
            room.camera()
            await asyncio.sleep(0.001)

    polling = asyncio.create_task(poll())
    try:
        with pytest.raises(RuntimeError, match="could not apply the priority area"):
            await room.node.set_region("scope", LASSO, "Dr. Chen")
    finally:
        polling.cancel()
        await asyncio.gather(polling, return_exceptions=True)
    # The failure reaches the caller, and the previous area is not quietly restored
    # behind a view that no longer shows it.
    await room.until(lambda: room.stage.codec.areas[-1] is None)
    assert "scope" not in room.node.regions
    assert room.area()["region"] is None and room.area()["region_unavailable"]


@pytest.mark.asyncio
async def test_a_stream_without_frames_does_not_claim_an_area(room, monkeypatch):
    await room.start()
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    await room.stop_frames()  # the camera stops delivering frames
    monkeypatch.setattr(local, "REGION_CONFIRM_SECONDS", 0.1)
    with pytest.raises(TimeoutError, match="did not confirm"):
        await room.node.set_region("scope", LASSO, "Dr. Chen")
    # The earlier area is requested again, not the one that was never confirmed.
    assert room.node.regions["scope"]["points"] == BOX
    assert room.node.regions["scope"]["by"] == "Dr. Rivera"
    request = room.node.workers["scope"]["settings"].with_suffix(region.REQUEST_SUFFIX)
    assert region.read_request(request)[1] == BOX


@pytest.mark.asyncio
async def test_a_cancelled_change_restores_the_previous_area(room):
    await room.start()
    await room.node.set_region("scope", BOX, "Dr. Rivera")
    await room.stop_frames()  # nothing confirms the next change
    change = asyncio.create_task(room.node.set_region("scope", LASSO, "Dr. Chen"))
    await asyncio.sleep(0.1)
    # The node's connection drops: the caller never hears back.
    change.cancel()
    with pytest.raises(asyncio.CancelledError):
        await change
    assert room.node.regions["scope"]["points"] == BOX
    assert room.node.regions["scope"]["by"] == "Dr. Rivera"
    request = room.node.workers["scope"]["settings"].with_suffix(region.REQUEST_SUFFIX)
    assert region.read_request(request)[1] == BOX
    assert not room.node.region_waiting


@pytest.mark.asyncio
async def test_worker_keeps_streaming_and_reports_again_when_its_status_cannot_be_written(
    tmp_path, monkeypatch
):
    path = settings_file(tmp_path)
    stage = video.Encode(Config(codec="h264"), path)
    stage.start()
    write, failures = region.write_status, []

    def full_disk(*args):
        failures.append(args)
        raise OSError("No space left on device")

    try:
        region.write_request(path.with_suffix(region.REQUEST_SUFFIX), 1, BOX)
        monkeypatch.setattr(region, "write_status", full_disk)
        assert stage.compute(FRAME) == (FRAME.header, b"frame")
        assert stage.compute(FRAME) == (FRAME.header, b"frame")
        assert len(failures) == 1 and status(path) == {}  # not retried on every frame
        monkeypatch.setattr(region, "write_status", write)
        stage.region_retry = 0
        stage.compute(FRAME)
        assert status(path) == {"supported": True, "blocked": "", "revision": 1, "error": ""}
        assert np.array_equal(stage.codec.areas[-1], region.mask(BOX))
    finally:
        stage.stop()


def patient_with(tmp_path, node, *, surgeons=(("lead", "Dr. Rivera", True),)):
    app = Application("patient", tmp_path / "patient")
    calls = []

    async def run(function, *args, **kwargs):
        return function(*args)

    async def node_call(key, method, params=None):
        calls.append((key, method, params))
        assert (key, method) == ("room", "camera.region")
        await node.set_region(params["id"], params.get("points"), params.get("by", ""))
        return {"cameras": node.inventory()["cameras"]}

    app.run, app.node_call, app.calls = run, node_call, calls
    app.nodes["room"] = {"status": "online", **node.inventory()}
    for peer, name, robot in surgeons:
        app.access.request(peer, name, robot)
        app.access.approve(peer, robot)
        app.peers[peer] = {"peer": None, "selected": {"room:scope"}}
    return app


@pytest.mark.asyncio
async def test_only_a_controlling_surgeon_viewing_the_camera_may_set_the_area(room, tmp_path):
    await room.start()
    patient = patient_with(
        tmp_path,
        room.node,
        surgeons=(("lead", "Dr. Rivera", True), ("observer", "Observer", False)),
    )
    lead, observer = SimpleNamespace(id="lead"), SimpleNamespace(id="observer")
    request = {"id": "room:scope", "points": BOX}
    with pytest.raises(PermissionError, match="View-only access cannot change the priority area"):
        await patient._request(observer, "camera.region", request)
    with pytest.raises(PermissionError, match="View-only"):
        await patient._request(observer, "camera.region", {"id": "room:scope", "points": None})
    patient.peers["lead"]["selected"] = set()
    with pytest.raises(PermissionError, match="Select the camera"):
        await patient._request(lead, "camera.region", request)
    patient.peers["lead"]["selected"] = {"room:scope", "room:gone"}
    with pytest.raises(ValueError, match="Camera is unavailable"):
        await patient._request(lead, "camera.region", {"id": "room:gone", "points": BOX})
    with pytest.raises(ValueError, match="larger"):
        await patient._request(lead, "camera.region", {"id": "room:scope", "points": BOX[:2] * 2})
    with pytest.raises(PermissionError, match="Patient approval"):
        await patient._request(SimpleNamespace(id="stranger"), "camera.region", request)
    assert patient.calls == [] and room.area() == NONE  # nothing reached the node

    # The reply carries the confirmed state, named after the approved surgeon.
    expected = {**NONE, "region": BOX, "region_by": "Dr. Rivera"}
    assert await patient._request(lead, "camera.region", request) == expected
    assert patient.calls == [
        ("room", "camera.region", {"id": "scope", "points": BOX, "by": "Dr. Rivera"})
    ]
    # Every viewer's status has it at once, the view-only observer included.
    public = next(c for c in patient.inventory()["cameras"] if c["id"] == "room:scope")
    assert {key: public[key] for key in STATE} == expected
    reply = await patient._request(observer, "status", {})
    assert {key: reply["cameras"][0][key] for key in STATE} == expected

    # The patient dashboard is the room's own authority: it may clear or set it too.
    assert await patient.action("camera.region", {"id": "room:scope", "points": None}) == NONE
    assert room.area() == NONE
    state = await patient.action("camera.region", {"id": "room:scope", "points": LASSO})
    assert state == {**NONE, "region": LASSO, "region_by": "the patient dashboard"}
    for bad in ({"points": BOX}, {"id": 7, "points": BOX}, {"id": "room:gone", "points": None}):
        with pytest.raises(ValueError, match="Camera is unavailable"):
            await patient.action("camera.region", bad)


@pytest.mark.asyncio
async def test_surgeon_dashboard_relays_the_area_through_patient_node_and_encoder(room, tmp_path):
    await room.start()
    patient = patient_with(tmp_path, room.node)
    surgeon = Application("surgeon", tmp_path / "surgeon")
    sent = []

    async def call(method, params=None, **kwargs):
        sent.append((method, params))
        try:
            return await patient._request(SimpleNamespace(id="lead"), method, params)
        except Exception as exc:  # A peer reports the patient's refusal as text.
            raise RuntimeError(str(exc)) from exc

    surgeon.remote = SimpleNamespace(closed=asyncio.Event(), call=call)
    public = next(c for c in patient.inventory()["cameras"] if c["id"] == "room:scope")
    surgeon.remote_status = {"status": "approved", "robot": True, "cameras": [dict(public)]}

    state = await surgeon.action("camera.region", {"id": "room:scope", "points": LASSO})
    assert state == {**NONE, "region": LASSO, "region_by": "Dr. Rivera"}
    assert sent == [("camera.region", {"id": "room:scope", "points": LASSO})]
    # The encoder has exactly the cells inside the surgeon's outline.
    assert np.array_equal(room.stage.codec.areas[-1], region.mask(LASSO))
    # The surgeon's own page shows it before the next status poll.
    shown = surgeon.remote_status["cameras"][0]
    assert {key: shown[key] for key in STATE} == state

    assert await surgeon.action("camera.region", {"id": "room:scope", "points": None}) == NONE
    assert surgeon.remote_status["cameras"][0]["region"] is None
    await room.until(lambda: room.stage.codec.areas[-1] is None)

    # The patient's reasons reach the surgeon unchanged.
    with pytest.raises(RuntimeError, match="Draw a larger priority area"):
        await surgeon.action(
            "camera.region",
            {"id": "room:scope", "points": [[0.5, 0.5], [0.51, 0.5], [0.51, 0.51]]},
        )
    # A view-only session is refused before anything is sent.
    sent.clear()
    surgeon.remote_status["robot"] = False
    with pytest.raises(PermissionError, match="View-only access cannot change the priority area"):
        await surgeon.action("camera.region", {"id": "room:scope", "points": BOX})
    assert sent == []
    surgeon.remote = None
    with contextlib.suppress(Exception):
        await surgeon.close()
