# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Independent Holoscan control graphs with bounded input and continuous feedback."""

import hashlib
import math
import secrets
import time
from concurrent.futures import Future
from threading import RLock

from telesurgery_core.transport.rpc import RequestRejected
from telesurgery_robots.adapters.base import (
    Adapter,
    controls,
    speed_value,
    validate_jog,
)
from telesurgery_robots.adapters.registry import adapter_type
from telesurgery_robots.mira.gripper import gripper_rates
from telesurgery_runtime.application.pipeline import Executor


class Controller:
    """All adapter I/O and lease changes run serially in this robot's graph."""

    def __init__(self, adapter: Adapter, specification, offset):
        self.adapter, self.specification, self.offset = adapter, specification, offset
        self.token, self.expires, self.sequence = None, 0.0, -1
        self.active = False
        self.closing = self.closed = False
        self.feedback = {"status": "starting", "state": None, "error": ""}
        self.connection_deadline = time.monotonic() + 60
        self.observed = self.next_poll = 0.0
        self.sample = 0
        self.stop_generation = 0

    def request_stop(self, token=None):
        """Latch only adapters with an explicitly thread-safe stop signal.

        The ordinary graph still confirms hold and changes ownership. This
        signal never calls vendor I/O concurrently with an existing operation.
        """
        if token is not None and self.token is not None and token != self.token:
            raise PermissionError("Control token is no longer valid")
        self.stop_generation += 1
        signal = getattr(self.adapter, "request_stop", None)
        if signal is not None:
            signal()

    def permitted(self):
        return self.adapter.simulation or self.specification().get("motion_enabled") is True

    def record(self, function, *, motion=False):
        if self.closing:
            raise RuntimeError("Robot controller is disconnected")
        try:
            state = function()
            if not isinstance(state, dict):
                raise RuntimeError("Controller returned invalid state")
        except Exception as exc:
            if motion and self.adapter.simulation and isinstance(exc, RequestRejected):
                # A rejected simulation movement is not a lost connection.
                # Confirm a hold before preserving the lease. Failure to hold
                # still marks feedback offline through the ordinary path.
                self.record(self.adapter.hold)
                raise
            # A freshly started vendor API may still be loading its lookup table.
            # Only initial transport failures get this bounded startup window.
            starting = (
                not self.sample
                and isinstance(exc, (ConnectionError, TimeoutError))
                and time.monotonic() < self.connection_deadline
            )
            self.feedback = {
                **self.feedback,
                "status": "starting" if starting else "offline",
                "error": "" if starting else str(exc),
            }
            self.next_poll = time.monotonic() + 2
            raise
        self.observed = time.monotonic()
        if motion:
            self.next_poll = min(
                self.next_poll, self.observed + getattr(self.adapter, "poll_interval", 0.1)
            )
        self.sample += 1
        self.feedback = {
            "status": "online",
            "error": "",
            "state": {**state, "sequence": self.sample, "observed_at": time.time()},
        }
        return self.feedback["state"]

    def report(self):
        value = self.feedback
        age = time.monotonic() - self.observed if self.observed else None
        return {
            **value,
            "simulation": self.adapter.simulation,
            "controls": controls(self.adapter, self.specification()),
            "feedback_age_ms": age * 1000 if age is not None else None,
            "stale": value["status"] != "online" or age is None or age > 1,
        }

    def state(self):
        return self.record(self.adapter.read)

    def prepare(self, token):
        if not self.adapter.groups:
            raise PermissionError("This adapter provides state feedback only")
        if not self.permitted():
            raise PermissionError("Physical motion must be enabled after supervised validation")
        if self.active and self.token != token:
            raise PermissionError("Controller is already owned or awaiting hold")
        state = self.state()
        self.token, self.expires, self.sequence = token, time.monotonic() + 2, -1
        self.active = True
        return state

    def validate(self, token):
        if not self.permitted():
            self.release()
            raise PermissionError("Physical motion is disabled on this node")
        if (
            not isinstance(token, str)
            or not self.token
            or not secrets.compare_digest(self.token, token)
            or time.monotonic() >= self.expires
        ):
            raise PermissionError("Patient controller lease expired")
        self.expires = time.monotonic() + 2

    def move(self, token, sequence, command, sent_at, mode="jog", speed_deg_s=None):
        if mode not in {"step", "jog", "velocity", "home", "grip", "cartesian", "follow", "reset"}:
            raise ValueError("Unknown robot motion mode")
        if type(sent_at) not in (float, int) or not math.isfinite(sent_at):
            raise ValueError("Invalid controller timestamp")
        age = time.time() + self.offset() - sent_at
        if age < -0.05:
            raise ValueError(f"Controller clock mismatch ({age * 1000:.0f} ms)")
        if age > 0.3:
            raise ValueError(
                f"Controller input expired in transit ({age * 1000:.0f} ms; limit 300 ms)"
            )
        self.validate(token)
        if type(sequence) is not int or sequence <= self.sequence:
            raise ValueError("Stale controller command")
        options = {}
        if hasattr(self.adapter, "speed_limits"):
            options["speed_deg_s"] = speed_value(speed_deg_s, self.adapter.speed_limits)
        elif speed_deg_s is not None:
            raise ValueError("Adjustable speed is not supported by this robot")
        if mode == "reset":
            if not self.adapter.simulation or not hasattr(self.adapter, "reset"):
                raise ValueError("Scene reset is not supported by this robot")
            if command != {}:
                raise ValueError("Scene reset uses the initial environment")
            self.sequence = sequence
            return self.record(self.adapter.reset, motion=True)
        if mode == "home":
            if command != {}:
                raise ValueError("Home uses the configured pose")
            if not hasattr(self.adapter, "home"):
                raise ValueError("Home is not supported by this robot")
            self.sequence = sequence
            return self.record(lambda: self.adapter.home(**options), motion=True)
        if mode == "grip":
            if not hasattr(self.adapter, "grip"):
                raise ValueError("Gripper control is not supported by this robot")
            gripper_rates(command, self.adapter.grippers, self.adapter.grip_speed)
            self.sequence = sequence
            return self.record(lambda: self.adapter.grip(command), motion=True)
        if mode == "follow":
            from telesurgery_robots.mira.follow import command as follow_command

            if not self.adapter.simulation or not hasattr(self.adapter, "follow_tool"):
                raise ValueError("MIRA target following is not supported by this robot")
            command = follow_command(command)
            self.sequence = sequence
            return self.record(lambda: self.adapter.follow_tool(command), motion=True)
        if mode == "cartesian":
            from telesurgery_robots.mira.cartesian import command as tool_command

            if not hasattr(self.adapter, "jog_cartesian"):
                raise ValueError("MIRA Cartesian jogging is not supported by this robot")
            command = tool_command(command, self.adapter.mira_cartesian)
            self.sequence = sequence
            return self.record(lambda: self.adapter.jog_cartesian(command), motion=True)
        if mode == "velocity":
            from telesurgery_robots.mira.velocity import command as velocity_command

            if not hasattr(self.adapter, "jog_velocity"):
                raise ValueError("Joint velocity control is not supported by this robot")
            command = velocity_command(command, self.adapter.joint_velocity)
            self.sequence = sequence
            return self.record(lambda: self.adapter.jog_velocity(command), motion=True)
        if isinstance(command, dict) and set(command) & {"translation", "rotation"}:
            from telesurgery_robots.adapters.base import cartesian_command

            if mode != "jog" or not hasattr(self.adapter, "cartesian"):
                raise ValueError("Cartesian jogging is not supported by this robot")
            command = cartesian_command(command)
        else:
            command = validate_jog(self.adapter, command)
        self.sequence = sequence
        # Most adapters already accept a finite target. A local servo adapter may
        # distinguish one step from a continuously refreshed gamepad target.
        move = (
            getattr(self.adapter, "step", self.adapter.jog) if mode == "step" else self.adapter.jog
        )
        return self.record(lambda: move(command, **options), motion=True)

    def renew(self, token):
        self.validate(token)
        return self.state()

    def replay_release(self, token, sent_at):
        """One bounded opening tick, authorized by the patient replay handoff.

        Keep the surgeon's command sequence intact. The patient serializes this
        operation with manual input, which revokes the completed pickup's consent.
        The ordinary gripper watchdog stops opening if replay polling stops.
        """
        if not self.adapter.simulation or self.specification().get("kind") != "versius-sim":
            raise PermissionError("Replay release is only available in Versius simulation")
        if (
            type(sent_at) not in (float, int)
            or not math.isfinite(sent_at)
            or not -0.05 <= time.time() + self.offset() - sent_at <= 0.3
        ):
            raise ValueError("Replay release expired in transit")
        self.validate(token)
        state = self.state()
        opening = state.get("grippers", {}).get("hand")
        if type(opening) not in (float, int) or not math.isfinite(opening):
            raise ValueError("Replay release requires measured gripper feedback")
        done = opening >= 0.998
        state = self.record(
            self.adapter.hold
            if done
            else lambda: self.adapter.grip(
                {"velocity": {"hand": min(0.375, (1.0 - opening) / 0.3)}}
            ),
            motion=True,
        )
        return {"done": done, "state": state}

    def hold(self, token):
        """Stop motion while preserving this surgeon's lease."""
        self.validate(token)
        return self.record(self.adapter.hold)

    def release(self, token=None):
        if not self.active:
            return True
        if token is not None and self.token is not None and self.token != token:
            raise PermissionError("Control token is no longer valid")
        self.token, self.expires = None, 0.0
        result = self.record(self.adapter.hold)
        self.active = False
        return result

    def tick(self):
        # This watchdog runs on the device, independently of the patient connection.
        if self.closing:
            return
        try:
            if self.active and (time.monotonic() >= self.expires or not self.permitted()):
                self.release()
            period = getattr(self.adapter, "poll_interval", 0.1)
            if time.monotonic() >= self.next_poll and time.monotonic() - self.observed >= period:
                self.state()
                self.next_poll = time.monotonic() + period
        except Exception:
            pass  # record() exposes the failure; retry feedback after a bounded delay.

    def close(self):
        if self.closed:
            return
        try:
            if not self.closing:
                self.release()
        finally:
            self.closing = True
            self.adapter.close()
            self.active = False
            self.closed = True


class Robots:
    def __init__(self, inventory):
        self.inventory = inventory
        self.devices, self.graphs, self.specs, self.errors = {}, {}, {}, {}
        self.clock_offset = 0.0
        self.lock = RLock()

    def sync(self):
        with self.lock:
            self._sync()

    def _sync(self):
        inventory = self.inventory()
        for key in list(self.devices):
            spec = inventory.get(key)
            # Enabling motion changes permissions, not the hardware connection.
            config = {k: v for k, v in (spec or {}).items() if k != "motion_enabled"}
            if config != self.specs[key]:
                self._close(key)
        self.errors.clear()
        for key, spec in inventory.items():
            if key in self.devices:
                continue
            try:
                factory = adapter_type(spec["kind"])
                if not spec.get(
                    "connection_enabled", not getattr(factory, "manages_connection", False)
                ):
                    self.errors[key] = {
                        "status": "disconnected",
                        "simulation": bool(getattr(factory, "simulation", False)),
                        "error": "",
                        "state": None,
                        "controls": {
                            "inputs": [],
                            "groups": {},
                            "reason": "Connect from the patient dashboard",
                        },
                        "stale": True,
                    }
                    continue
                adapter = factory(spec)
                controller = Controller(
                    adapter,
                    lambda key=key: self.inventory().get(key, {}),
                    lambda: self.clock_offset,
                )
                name = "robot_" + hashlib.sha256(key.encode()).hexdigest()[:12]
                graph = Executor(
                    name, idle=controller.tick, interval=getattr(adapter, "control_period", 0.1)
                ).start()
                self.devices[key], self.graphs[key] = controller, graph
                self.specs[key] = {k: v for k, v in spec.items() if k != "motion_enabled"}
            except Exception as exc:
                self.errors[key] = {
                    "status": "unsupported",
                    "error": str(exc),
                    "state": None,
                    "controls": {"inputs": [], "groups": {}},
                    "stale": True,
                }

    def report(self):
        return {
            **self.errors,
            **{key: device.report() for key, device in tuple(self.devices.items())},
        }

    def submit(self, method, key, **params):
        device, graph = self.devices.get(key), self.graphs.get(key)
        if device is None or graph is None:
            future = Future()
            future.set_exception(
                RuntimeError(self.errors.get(key, {}).get("error") or "Controller is unavailable")
            )
            return future
        function = getattr(device, method)
        if method in {"hold", "release", "close"}:
            device.request_stop(params.get("token"))
        generation = device.stop_generation

        def invoke():
            if method in {"move", "replay_release"} and generation != device.stop_generation:
                raise RuntimeError("Robot input cancelled by Stop")
            return function(**params)

        return graph.submit(
            invoke,
            timeout=0.2
            if method in {"move", "replay_release"}
            else 5
            if method in {"hold", "release", "close"}
            else 2,
        )

    def _close(self, key):
        device = self.devices[key]
        try:
            if not device.closed:
                self.submit("close", key).result(timeout=3)
            self.graphs[key].close()
        except Exception as exc:
            device.feedback = {
                **device.feedback,
                "status": "offline",
                "error": f"Disconnect failed: {str(exc) or type(exc).__name__}",
            }
            raise
        self.graphs.pop(key)
        self.devices.pop(key)
        self.specs.pop(key)

    def close(self):
        with self.lock:
            errors = []
            for key in list(self.devices):
                try:
                    self._close(key)
                except Exception as exc:
                    errors.append(str(exc))
            self.errors.clear()
            if errors:
                raise RuntimeError("; ".join(errors))
