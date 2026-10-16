# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Long-lived patient ownership never extends the device's short motion watchdog."""

import asyncio
import secrets
import time
from types import SimpleNamespace

import pytest
from telesurgery.server.application import Application
from telesurgery_core.control.access import Ownership
from telesurgery_runtime.application.robots import Controller


@pytest.fixture
def patient(tmp_path):
    class Adapter:
        simulation = True
        groups = {"axis": 1}
        max_step_deg = 0.4
        moves = holds = 0
        fail_hold = False

        def read(self):
            return {"joints_deg": {"axis": [self.moves * 0.1]}}

        def jog(self, command):
            self.moves += 1
            return self.read()

        def hold(self):
            self.holds += 1
            if self.fail_hold:
                raise RuntimeError("Stop not confirmed")
            return self.read()

    app = Application("patient", tmp_path)
    app.now = [time.monotonic()]
    app.device = Controller(Adapter(), lambda: {}, lambda: 0)
    app.calls = []

    async def run(function, *args, **kwargs):
        return function(*args)

    async def node_call(node, method, params):
        app.calls.append(method)
        return getattr(app.device, method.removeprefix("robot."))(
            **{key: value for key, value in params.items() if key != "key"}
        )

    app.run, app.node_call = run, node_call
    app.credential = secrets.token_urlsafe(32)
    app.access.request("one", "Surgeon", True, app.credential)
    app.access.approve("one", True)
    app.access.request("two", "Surgeon", True, secrets.token_urlsafe(32))
    app.access.approve("two", True)
    app.nodes["node"] = {
        "status": "online",
        "robots": [{"id": "arm", "name": "Arm", "kind": "fixture", "controls": {}}],
    }
    app.owners["node:arm"] = Ownership(clock=lambda: app.now[0])
    return app


async def acquire(patient):
    result = await patient._robot("one", "robot.acquire", {"id": "node:arm"})
    return {"id": "node:arm", "token": result["token"]}


@pytest.mark.asyncio
async def test_device_watchdog_stops_without_surrendering_patient_lock(patient):
    credentials = await acquire(patient)
    owner = patient.owners["node:arm"]
    deadline = owner.expires
    patient.device.expires = 0
    patient.device.tick()
    assert not patient.device.active and patient.device.adapter.holds == 1
    patient.now[0] += 20
    await patient._robot("one", "robot.renew", credentials)
    assert patient.calls[-3:] == ["robot.renew", "robot.release", "robot.prepare"]
    assert owner.owner == "one" and owner.expires == deadline
    assert patient.device.adapter.moves == 0
    with pytest.raises(PermissionError, match="another surgeon"):
        await patient._robot("two", "robot.acquire", {"id": "node:arm"})
    await patient._robot(
        "one",
        "robot.move",
        {**credentials, "sequence": 1, "command": {"axis": [0.1]}, "sent_at": time.time()},
    )
    assert patient.device.adapter.moves == 1
    assert owner.expires == patient.now[0] + 300
    patient.now[0] = owner.expires
    with pytest.raises(PermissionError, match="expired"):
        await patient._robot("one", "robot.renew", credentials)
    assert owner.owner is None and not patient.device.active


@pytest.mark.asyncio
async def test_recovery_requires_confirmed_stop_and_never_retries_motion(patient):
    credentials = await acquire(patient)
    patient.device.expires = 0
    patient.device.adapter.fail_hold = True
    with pytest.raises(RuntimeError, match="Stop not confirmed"):
        await patient._robot("one", "robot.renew", credentials)
    assert patient.calls[-1] == "robot.release"
    assert patient.device.adapter.moves == 0
    assert patient.owners["node:arm"].owner == "one"
    patient.device.adapter.fail_hold = False
    await patient._robot("one", "robot.hold", credentials)
    assert patient.device.active
    await patient.action("robot.revoke", {"id": "node:arm"})
    before = list(patient.calls)
    with pytest.raises(PermissionError, match="expired"):
        await patient._robot("one", "robot.renew", credentials)
    assert patient.calls == before


@pytest.mark.asyncio
async def test_expired_input_cannot_keep_idle_lock_alive(patient):
    credentials = await acquire(patient)
    owner = patient.owners["node:arm"]
    deadline = owner.expires
    patient.now[0] += 20
    with pytest.raises(ValueError, match="expired in transit"):
        await patient._robot(
            "one",
            "robot.move",
            {**credentials, "sequence": 1, "command": {"axis": [0.1]}, "sent_at": time.time() - 1},
        )
    assert owner.expires == deadline


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_same_authenticated_service_resumes_only_unexpired_ownership(patient, expired):
    credentials = await acquire(patient)
    owner = patient.owners["node:arm"]
    await patient._suspend_owner("one")
    patient.access.disconnect("one")
    assert not patient.device.active
    assert patient.inventory()["robots"][0]["owner"] == "Surgeon"
    if expired:
        patient.now[0] = owner.expires
    else:
        with pytest.raises(PermissionError, match="another surgeon"):
            await patient._robot("two", "robot.acquire", {"id": "node:arm"})
    reply = await patient._request(
        SimpleNamespace(id="returning"),
        "access.request",
        {"name": "Surgeon", "robot": True, "credential": patient.credential},
    )
    assert reply["status"] == "approved"
    assert reply["control_tokens"] == ({} if expired else {"node:arm": credentials["token"]})
    assert owner.owner == (None if expired else "returning")
    assert patient.device.adapter.moves == 0
    if not expired:
        await patient._robot("returning", "robot.renew", credentials)
        assert patient.device.active


@pytest.mark.asyncio
async def test_patient_can_revoke_disconnected_surgeon_and_block_resume(patient):
    await acquire(patient)
    owner = patient.owners["node:arm"]
    await patient._suspend_owner("one")
    patient.access.disconnect("one")
    await patient.action("access.revoke", {"id": "remembered:" + owner.identity})
    assert owner.owner is None
    reply = await patient._request(
        SimpleNamespace(id="returning"),
        "access.request",
        {"name": "Surgeon", "robot": True, "credential": patient.credential},
    )
    assert reply["status"] == "pending" and not reply["control_tokens"]


@pytest.mark.asyncio
async def test_inactive_lock_expires_without_another_request(patient):
    await acquire(patient)
    owner = patient.owners["node:arm"]
    patient.now[0] = owner.expires
    watch = asyncio.create_task(patient._watch())
    try:
        async with asyncio.timeout(2):
            while owner.owner:
                await asyncio.sleep(0.01)
        assert not patient.device.active
        assert patient.device.adapter.moves == 0
    finally:
        watch.cancel()
        await asyncio.gather(watch, return_exceptions=True)
