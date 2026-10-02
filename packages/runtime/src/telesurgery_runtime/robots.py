# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Patient-node robot adapters. Every method is invoked inside its Holoscan endpoint."""

import math
import secrets
import time

from telesurgery_core.adapters.mira import delta
from telesurgery_core.adapters.sim_robot import values
from telesurgery_core.transport.rpc import RpcClient


class Robots:
    def __init__(self, inventory):
        self.inventory = inventory
        self.devices = {}
        self.clock_offset = 0.0

    def _device(self, key):
        if key not in self.devices:
            spec = self.inventory()[key]
            if spec.get("kind") not in {"mira-sim", "franka-sim"}:
                raise ValueError("No supported controller adapter for this robot")
            self.devices[key] = {
                "client": RpcClient(spec["uri"]),
                "token": None,
                "expires": 0.0,
                "sequence": -1,
                "kind": spec["kind"],
            }
        return self.devices[key]

    def prepare(self, key, token):
        device = self._device(key)
        self.expire()
        if device["token"] and device["token"] != token:
            raise PermissionError("Controller is already owned")
        device.update(token=token, expires=time.monotonic() + 2, sequence=-1)
        return self.state(key)

    def validate(self, key, token):
        device = self._device(key)
        if (
            not isinstance(token, str)
            or not device["token"]
            or not secrets.compare_digest(device["token"], token)
            or time.monotonic() >= device["expires"]
        ):
            raise PermissionError("Patient controller lease expired")
        device["expires"] = time.monotonic() + 2
        return device

    def move(self, key, token, sequence, command, sent_at):
        if (
            type(sent_at) not in (float, int)
            or not math.isfinite(sent_at)
            or not -0.05 <= time.time() + self.clock_offset - sent_at <= 0.3
        ):
            raise ValueError("Controller input expired in transit")
        device = self.validate(key, token)
        if type(sequence) is not int or sequence <= device["sequence"]:
            raise ValueError("Stale controller command")
        if device["kind"] == "mira-sim":
            request = delta(values(command.get("left"), 4, 5), values(command.get("right"), 4, 5))
        else:
            request = {
                "jsonrpc": "2.0",
                "method": "set_joint_delta",
                "params": {"joints": values(command.get("joints"), 7, 5)},
            }
        device["sequence"] = sequence
        return device["client"].send(request)

    def renew(self, key, token):
        self.validate(key, token)
        return self.state(key)

    def release(self, key, token=None):
        device = self.devices.get(key)
        if device is None:
            return True
        if token is not None and device["token"] != token:
            raise PermissionError("Control token is no longer valid")
        device["token"], device["expires"] = None, 0
        return device["client"].send({"jsonrpc": "2.0", "method": "hold", "params": {}})

    def state(self, key):
        return self._device(key)["client"].send(
            {"jsonrpc": "2.0", "method": "get_state", "params": {}}
        )

    def expire(self):
        for key, device in self.devices.items():
            if device["token"] and time.monotonic() >= device["expires"]:
                self.release(key)

    def close(self):
        errors = []
        for key, device in self.devices.items():
            try:
                self.release(key)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                device["client"].close()
        self.devices.clear()
        if errors:
            raise RuntimeError("; ".join(errors))
