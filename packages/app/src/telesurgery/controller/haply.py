# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Local Inverse3/VerseGrip input and bounded robot simulation mappings."""

import json
import math
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from telesurgery.controller.input import Inputs

NAME = "Haply Inverse3"
MAX_AGE = 0.2
GRIP_HOLD = 0.6


def available(sysfs=Path("/sys/class/tty"), dev=Path("/dev")):
    """Discover visible Haply USB endpoints without opening them or starting tracking."""
    for endpoint in sysfs.glob("ttyACM*"):
        if not (dev / endpoint.name).exists():
            continue
        for parent in endpoint.resolve().parents:
            try:
                product = (parent / "product").read_text().strip().casefold()
            except OSError:
                continue
            if product in {"haply inverse3", "haply usb transceiver"}:
                return True
    return False


@dataclass(frozen=True)
class Sample:
    identity: tuple[str, str]
    position: tuple[float, ...]
    orientation: tuple[float, float, float, float]
    buttons: frozenset[str]
    received: float
    generation: int = 0


def devices(data):
    arms, grips = data.get("inverse3", []), data.get("wireless_verse_grip", [])
    if len(arms) != 1 or len(grips) != 1:
        raise ValueError("Connect one Inverse3 base and one wireless VerseGrip.")
    return arms[0], grips[0]


def decode(data, received, generation=0):
    arm, grip = devices(data)
    if not arm.get("status", {}).get("calibrated"):
        raise ValueError("Calibrate the Inverse3 at its magnetic calibration point.")
    if not all(arm["status"].get(key) for key in ("ready", "started")):
        raise ValueError("Inverse3 is not ready.")
    if not all(grip.get("status", {}).get(key) for key in ("connected", "awake", "ready")):
        raise ValueError("Wake the VerseGrip with its power button.")
    try:
        position = tuple(float(arm["state"]["cursor_position"][axis]) for axis in "xyz")
        quat = tuple(float(grip["state"]["orientation"][axis]) for axis in "xyzw")
        buttons = grip["state"]["buttons"]
        if not all(type(buttons[key]) is bool for key in "abc"):
            raise ValueError
        if not all(math.isfinite(v) for v in (*position, *quat)):
            raise ValueError
        norm = math.hypot(*quat)
        if not 0.5 < norm < 1.5:
            raise ValueError
        x, y, z, w = (v / norm for v in quat)
        identity = arm["device_id"], grip["device_id"]
        if not all(isinstance(key, str) and key for key in identity):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid Haply tracking data.") from exc
    return Sample(
        identity,
        position,
        (x, y, z, w),
        frozenset(k for k in "abc" if buttons[k]),
        received,
        generation,
    )


def rotation_delta(previous, current):
    """Quaternion distance and twist about the grip's local +Y pointing axis."""
    px, py, pz, pw = previous
    x, y, z, w = current
    scalar = px * x + py * y + pz * z + pw * w
    twist = pw * y - py * w - pz * x + px * z
    if scalar < 0:  # q and -q describe the same orientation.
        scalar, twist = -scalar, -twist
    distance = math.degrees(2 * math.acos(min(1.0, max(0.0, scalar))))
    return distance, math.degrees(2 * math.atan2(twist, scalar))


def pen_tilt(orientation):
    """Elevation of the grip's +Y pointing axis in Haply's Z-up frame.

    Using the pointing direction keeps tilt independent of axial roll and yaw.
    """
    x, y, z, w = orientation
    direction = (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w))
    return math.degrees(math.atan2(direction[2], math.hypot(*direction[:2])))


class Haply:
    """One background reader; only the newest sample reaches the UI, never a queue."""

    def __init__(self):
        self.latest = (None, "Connecting to Haply…")
        self.done = threading.Event()
        self.process = None
        self.log = None
        self.thread = threading.Thread(target=self._run, name="haply-input", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            import websocket
        except ImportError:
            self.latest = None, "Haply needs python3-websocket; run setup.sh on this host."
            return
        generation = 0
        try:
            while not self.done.is_set():
                connection = None
                try:
                    connection = websocket.create_connection(
                        "ws://127.0.0.1:10001", timeout=MAX_AGE, http_no_proxy=["127.0.0.1"]
                    )
                    generation += 1
                    data = json.loads(connection.recv())
                    while not self.done.is_set():
                        # Monitoring probes do not apply force or change device configuration.
                        request = {"session": {"force_render_full_state": {}}}
                        for family, command in (
                            ("inverse3", "probe_position"),
                            ("wireless_verse_grip", "probe_orientation"),
                        ):
                            request[family] = [
                                {"device_id": item["device_id"], "commands": {command: {}}}
                                for item in data.get(family, [])
                            ]
                        sent = time.monotonic()
                        connection.send(json.dumps(request))
                        data = json.loads(connection.recv())
                        try:
                            sample = decode(data, sent, generation)
                            self.latest = sample, ""
                        except ValueError as exc:
                            self.latest = None, str(exc)
                        self.done.wait(0.01)
                except ConnectionRefusedError:
                    executable = shutil.which("haply-inverse-service")
                    self.latest = (
                        None,
                        "Haply service unavailable; open Haply Hub or run setup.sh on this host.",
                    )
                    if executable and self.process is None:
                        self.log = tempfile.TemporaryFile()
                        self.process = subprocess.Popen(
                            [executable],
                            stdin=subprocess.DEVNULL,
                            stdout=self.log,
                            stderr=self.log,
                        )
                except (OSError, websocket.WebSocketException, ValueError, KeyError, TypeError):
                    self.latest = None, "Haply connection lost; reconnect the base and grip."
                finally:
                    if connection is not None:
                        connection.close()
                self.done.wait(0.5)
        finally:
            if self.process is not None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.log is not None:
                self.log.close()

    def sample(self, now):
        sample, error = self.latest
        if sample is not None and not 0 <= now - sample.received < MAX_AGE:
            return None, "Haply tracking timed out."
        return sample, error

    def close(self):
        self.done.set()
        self.thread.join(timeout=5)


class MiraHaply:
    """Follow the latest pen pose, with separate start/stop and arm-switch buttons."""

    dual = True
    initial_arm = "left"

    def __init__(self):
        self.arm = self.initial_arm
        self.halt()

    def halt(self):
        self.paused = True
        self.neutral = False
        self.buttons = frozenset()
        self.previous = None
        self.anchor = None
        self.origin = None
        self.rotation = 0.0
        self.active = False
        self.button_since = None
        self.button_held = False
        self.last_sent = float("-inf")
        self.error = ""

    def rebase(self, sample, state):
        self.anchor = sample
        self.rotation = 0.0
        self.origin = None
        try:
            pose = state["cartesian_mm_deg"][self.arm]
            roll = state["joints_deg"][self.arm][4]
            values = [float(v) for v in (*pose, roll)]
            if len(values) != 5 or not all(math.isfinite(v) for v in values):
                raise ValueError
            self.origin = values
        except (KeyError, IndexError, TypeError, ValueError):
            self.error = "Waiting for MIRA tool-position feedback."

    def update(self, sample, state, inputs, now, *, ready=True):
        if sample is None or not 0 <= now - sample.received < MAX_AGE:
            self.halt()
            return "release", {}
        previous, self.previous = self.previous, sample
        if previous is not None and (
            sample.identity != previous.identity
            or sample.generation != previous.generation
            or sample.received - previous.received > MAX_AGE
            or math.dist(sample.position, previous.position) > 0.05
            or rotation_delta(previous.orientation, sample.orientation)[0] > 45
        ):
            self.halt()
            return "release", {}
        buttons, old_buttons = sample.buttons, self.buttons
        self.buttons = buttons
        if "c" in buttons or {"a", "b"} <= buttons:
            # Calibration and ambiguous simultaneous presses stop motion.
            self.halt()
            return "release", {}
        if not self.neutral:
            self.neutral = not ({"a", "b"} & buttons)
            self.rebase(sample, state)
            return None
        pressed = buttons & {"a", "b"}
        was_pressed = old_buttons & {"a", "b"}
        if pressed and pressed != was_pressed:
            self.button_since, self.button_held = now, False
            self.rebase(sample, state)
            self.active = False
            return "release", {}
        if pressed:
            self.rebase(sample, state)
            if self.button_since is None or now - self.button_since < GRIP_HOLD:
                return None
            self.button_held = True
            if self.paused or not ready or now - self.last_sent < 0.05 - 1e-9:
                return None
            if not self.dual and not state.get("gripper_available"):
                return None
            if self.grip_position(state) is None:
                return "release", {}
            self.last_sent, self.active = now, True
            return "grip", {self.arm: inputs.grip_speed * (-1 if "a" in pressed else 1)}
        if was_pressed:
            if not self.button_held:
                if "a" in was_pressed:
                    self.paused = not self.paused
                elif self.dual:
                    self.arm = "right" if self.arm == "left" else "left"
            self.button_since, self.button_held = None, False
            self.rebase(sample, state)
            self.active = False
            return "release", {}
        if self.paused:
            self.rebase(sample, state)
            return None
        if self.anchor is None or self.origin is None:
            self.rebase(sample, state)
            return None
        if previous is not None:
            self.rotation += rotation_delta(previous.orientation, sample.orientation)[1]
        if not ready or now - self.last_sent < 0.05 - 1e-9:
            return None
        return self.motion(sample, state, inputs, now)

    def motion(self, sample, state, inputs, now):
        try:
            pose = state["cartesian_mm_deg"][self.arm]
            current_roll = state["joints_deg"][self.arm][4]
            measured = [float(v) for v in (*pose, current_roll)]
            if len(measured) != 5 or not all(math.isfinite(v) for v in measured):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            self.halt()
            self.error = "Waiting for MIRA tool-position feedback."
            return "release", {}
        self.error = ""
        delta = [a - b for a, b in zip(sample.position, self.anchor.position, strict=True)]
        config = inputs.controls["mira_cartesian"]
        # Keep the vendor-frame mapping as the default; simulation publishes
        # its different base axes so pen up/right/forward follow the work area.
        basis = config.get("haply_basis", ((0, 1, 0), (-1, 0, 0), (0, 0, 1)))
        target = [
            self.origin[i] + 700 * sum(a * b for a, b in zip(row, delta, strict=True))
            for i, row in enumerate(basis)
        ]
        # Decreasing MIRA's elbow angle raises the jaws on either arm.
        # Preserve the reference captured on Start, without changing XYZ.
        tilt = pen_tilt(sample.orientation) - pen_tilt(self.anchor.orientation)
        target_elbow = self.origin[3] - tilt
        elbow = (target_elbow - measured[3] + 180) % 360 - 180
        translation = [a - b for a, b in zip(target, measured[:3], strict=True)]
        # Nodes that retain commanded tool targets report them separately from
        # measured pose. Subtract that target to avoid requesting the same
        # unfinished travel again, while still waiting for actual arrival.
        following = math.hypot(*translation) > 0.05 or abs(elbow) > 0.1
        planned = state.get("cartesian_target_mm_deg", {}).get(self.arm)
        if planned is not None:
            if len(planned) != 4 or not all(math.isfinite(v) for v in planned):
                self.halt()
                self.error = "Waiting for MIRA tool-target feedback."
                return "release", {}
            translation = [a - b for a, b in zip(target, planned[:3], strict=True)]
            elbow = (target_elbow - planned[3] + 180) % 360 - 180
        linear = config["linear_step_mm"] * inputs.arm_percent / 100
        angular = config["angular_step_deg"] * inputs.arm_percent / 100
        roll = config.get("roll_step_deg", config["angular_step_deg"]) * inputs.roll_percent / 100
        length = math.hypot(*translation)
        values = [0.0] * 5
        if length > 0.05:
            values[:3] = [v * min(1, linear / length) for v in translation]
        if abs(elbow) > 0.1:
            values[3] = max(-angular, min(angular, elbow))
        target_roll = max(-180, min(180, self.origin[4] + self.rotation))
        if abs(target_roll - measured[4]) > 0.5:
            values[4] = max(-roll, min(roll, target_roll - measured[4]))
        if not any(values) and not (planned is not None and following):
            release, self.active = self.active, False
            return ("release", {}) if release else None
        command = {"left": [0.0] * 5, "right": [0.0] * 5}
        command[self.arm] = values
        self.last_sent, self.active = now, True
        return "cartesian", command

    def grip_position(self, state):
        try:
            position = float(state["grippers"][self.arm])
            if not math.isfinite(position) or not 0 <= position <= 1:
                raise ValueError
            return position
        except (KeyError, TypeError, ValueError):
            self.halt()
            self.error = "Waiting for gripper feedback."
            return None


def supports(robot):
    controls = robot.get("controls", {})
    return bool(
        robot.get("kind") == "mira-sim"
        and controls.get("mira_cartesian")
        or robot.get("kind") in {"franka-sim", "versius-sim"}
        and controls.get("cartesian")
    )


def mapper_for(robot):
    return CartesianHaply() if robot.get("kind") in {"franka-sim", "versius-sim"} else MiraHaply()


class CartesianHaply(MiraHaply):
    """Follow a clutched six-axis pen pose through the ordinary Cartesian jog API."""

    dual = False
    initial_arm = "hand"

    @staticmethod
    def rotation_matrix(quaternion):
        import numpy as np

        x, y, z, w = quaternion
        return np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )

    @staticmethod
    def pose(state):
        import numpy as np

        tool = state["tool_pose"]
        position = np.asarray(tool["position_m"], dtype=float)
        rotation = np.asarray(tool["orientation_matrix"], dtype=float)
        if (
            position.shape != (3,)
            or rotation.shape != (3, 3)
            or not np.isfinite(position).all()
            or not np.isfinite(rotation).all()
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3)
            or np.linalg.det(rotation) < 0.99
        ):
            raise ValueError("Invalid tool pose")
        return position, rotation

    def rebase(self, sample, state):
        self.anchor, self.origin, self.rotation = sample, None, 0.0
        try:
            self.origin = self.pose(state)
            self.error = ""
        except (KeyError, TypeError, ValueError):
            self.error = "Waiting for robot tool-position feedback."

    def motion(self, sample, state, inputs, now):
        import numpy as np

        try:
            position, orientation = self.pose(state)
        except (KeyError, TypeError, ValueError):
            self.halt()
            self.error = "Waiting for robot tool-position feedback."
            return "release", {}
        if state.get("stopping"):
            # Reaching the pen target requests a normal, decelerated hold.
            # Wait for that ramp before following the pen again; a controller
            # fault still requires an explicit restart.
            if state.get("stop_reason") == "released":
                return None
            self.halt()
            self.error = state.get("stop_reason") or "Robot motion stopped."
            return "release", {}
        self.error = ""
        basis = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
        target = self.origin[0] + 0.7 * basis @ (np.asarray(sample.position) - self.anchor.position)
        # Grip +Y points along the pen; tool +Z points along the probe. Capture
        # their alignment on Start so axial pen twist rotates the probe itself.
        mount = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
        relative = self.rotation_matrix(self.anchor.orientation).T @ self.rotation_matrix(
            sample.orientation
        )
        desired = self.origin[1] @ mount @ relative @ mount.T
        error = desired @ orientation.T
        angle = math.acos(float(np.clip((np.trace(error) - 1) / 2, -1, 1)))
        axis = np.array(
            [error[2, 1] - error[1, 2], error[0, 2] - error[2, 0], error[1, 0] - error[0, 1]]
        )
        if angle > math.radians(90):
            self.halt()
            self.error = "Pen orientation exceeded the following range."
            return "release", {}
        angular = axis * angle / max(1e-9, np.linalg.norm(axis))
        linear = target - position
        if np.linalg.norm(linear) < 0.00025:
            linear[:] = 0
        if np.linalg.norm(angular) < math.radians(0.3):
            angular[:] = 0
        if not np.any(linear) and not np.any(angular):
            release, self.active = self.active, False
            return ("release", {}) if release else None
        scale = inputs.speed / 20
        # Slow down on approach. Both vectors remain inside the same validated
        # velocity envelope as keyboard/gamepad, including the node watchdog.
        linear = linear * 2 / max(1e-9, 0.1 * scale)
        angular = angular * 2 / max(1e-9, math.radians(30) * scale)
        angular *= inputs.roll_percent / 50
        linear /= max(1, np.linalg.norm(linear))
        angular /= max(1, np.linalg.norm(angular))
        self.last_sent, self.active = now, True
        return "jog", {"translation": linear.tolist(), "rotation": angular.tolist()}


class BrowserHaply:
    """Map browser polls with the same rules as Tk; the browser submits robot commands."""

    def __init__(self):
        self.reader = None
        self.mapper = MiraHaply()
        self.identity = None
        self.last_read = 0

    def read(self, robot, params):
        if not supports(robot):
            raise ValueError("Haply input supports MIRA, Franka and Versius simulation.")
        expected = MiraHaply if robot["kind"] == "mira-sim" else CartesianHaply
        if type(self.mapper) is not expected:
            self.mapper = expected()
        token = params.get("token")
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise ValueError("Haply input requires a browser session token.")
        inputs = Inputs(robot)
        speeds = params.get("speeds", {})
        if not isinstance(speeds, dict):
            raise ValueError("Input speeds must be an object.")
        for kind in ("arm", "roll", "grip"):
            value = speeds.get(kind, getattr(inputs, kind + "_percent"))
            if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 100:
                raise ValueError("Input speeds must be between 1 and 100 percent.")
            setattr(inputs, kind + "_percent", value)
        now = time.monotonic()
        identity = (
            robot["id"],
            token,
            inputs.arm_percent,
            inputs.roll_percent,
            inputs.grip_percent,
        )
        if identity != self.identity or now - self.last_read >= MAX_AGE:
            self.mapper.halt()
        self.identity, self.last_read = identity, now
        if self.reader is None:
            self.reader = Haply()
        sample, error = self.reader.sample(now)
        if params.get("enabled") is not True:
            self.mapper.halt()
            request = None
        else:
            request = self.mapper.update(sample, robot.get("state") or {}, inputs, now)
        return {
            "request": request,
            "paused": self.mapper.paused,
            "arm": self.mapper.arm,
            "error": error or self.mapper.error,
        }

    def close(self):
        reader, self.reader = self.reader, None
        self.mapper.halt()
        self.identity = None
        if reader:
            reader.close()
