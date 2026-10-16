# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Desktop input mappings, matching the browser's keyboard and standard gamepad."""

import math

PAIRS = ("qa", "ws", "ed", "rf", "tg", "yh", "uj", "ik")
ARM_PAIRS = {"left": ("qa", "ws", "ed", "rf", "tg"), "right": ("uj", "ik", "ol", "p;", "yh")}
TOOL_KEYS = {
    "w": ("translation", 0, 1),
    "s": ("translation", 0, -1),
    "a": ("translation", 1, 1),
    "d": ("translation", 1, -1),
    "r": ("translation", 2, 1),
    "f": ("translation", 2, -1),
    "q": ("rotation", 2, 1),
    "e": ("rotation", 2, -1),
    "left": ("rotation", 0, 1),
    "right": ("rotation", 0, -1),
    "up": ("rotation", 1, -1),
    "down": ("rotation", 1, 1),
}
GRIP_KEYS = {"hand": "zx", "left": "zx", "right": "nm"}


def deadzone(value):
    return math.copysign(max(0, min(1, abs(value)) - 0.15) / 0.85, value)


class Keyboard:
    """Coalesce Linux autorepeat pairs without allowing a held key to rearm after Stop."""

    def __init__(self):
        self.down = set()
        self.pending = {}
        self.active = {}

    def press(self, key, now, allowed=True):
        self.pending.pop(key, None)
        fresh = key not in self.down
        self.down.add(key)
        if fresh and allowed:
            self.active[key] = now
        return fresh and allowed

    def release(self, key, now):
        if key in self.down:
            self.pending[key] = now + 0.02

    def poll(self, now):
        for key, deadline in list(self.pending.items()):
            if now >= deadline:
                del self.pending[key]
                self.down.discard(key)
                self.active.pop(key, None)

    def halt(self):
        self.active.clear()


class Inputs:
    def __init__(self, robot):
        self.controls = robot["controls"]
        self.hold_grip = robot.get("kind") == "versius-sim"
        self.groups = self.controls.get("groups", {})
        self.dual = set(self.groups) == {"left", "right"}
        self.mode = "cartesian" if self.controls.get("cartesian") else "joints"
        self.keyboard = Keyboard()
        self.arm_percent = self.controls.get("default_arm_speed_percent", 20)
        self.roll_percent = self.controls.get("default_roll_speed_percent", 50)
        self.grip_percent = self.controls.get("default_grip_speed_percent", 40)
        self.last_sent = self.last_jog = float("-inf")
        self.last_grip = {}
        self.last_mode = None
        self.joint_active = False
        self.stepped = set()
        self.continuous = False
        self.armed = False
        self.alternate = False
        self.grip_target = None
        self.toggle_ready = False
        self.home_button = None
        self.home_since = None
        self.home_ready = False

    @property
    def speed(self):
        limit = self.controls.get("speed_deg_s", {})
        maximum = limit.get(
            "max",
            self.controls.get("joint_velocity", {}).get(
                "arm_deg_s", self.controls.get("max_step_deg", 0.2) * 20
            ),
        )
        return max(limit.get("min", 0), maximum * self.arm_percent / 100)

    @property
    def grip_speed(self):
        return self.controls.get("grip_speed_pct_s", {}).get("max", 50) * self.grip_percent / 10000

    def increment(self, index, seconds):
        maximum = self.controls.get("max_step_deg", self.controls.get("step_deg", 0.2))
        roll = self.controls.get("joint_velocity", {}).get("roll_deg_s", maximum * 20)
        speed = roll * self.roll_percent / 100 if self.dual and index == 4 else self.speed
        if self.mode == "joints" and self.controls.get("joint_velocity"):
            return speed
        return min(maximum, speed * seconds)

    def bindings(self):
        if self.mode == "cartesian":
            return TOOL_KEYS
        result = {}
        for group, count in self.groups.items():
            for index, pair in enumerate((ARM_PAIRS[group] if self.dual else PAIRS)[:count]):
                for key, sign in zip(pair, (1, -1), strict=True):
                    result[key] = (group, index, sign)
        return result

    def halt(self):
        self.keyboard.halt()
        self.stepped.clear()
        self.continuous = False
        self.armed = self.home_ready = self.toggle_ready = False
        self.home_since = self.home_button = self.grip_target = None
        self.last_grip = {}
        self.last_jog = float("-inf")
        self.joint_active = False

    def _empty(self):
        if self.mode == "cartesian":
            return {"translation": [0.0] * 3, "rotation": [0.0] * 3}
        return {group: [0.0] * count for group, count in self.groups.items()}

    def _tool(self, command):
        if self.mode != "mira-tool":
            return command
        config = self.controls["mira_cartesian"]
        maximum = self.controls.get("max_step_deg", 1)
        rates = self.controls.get("joint_velocity", {})
        result = {}
        for group, values in command.items():
            values = [
                v
                / (rates.get("roll_deg_s" if i == 4 else "arm_deg_s", maximum * 20) / 20)
                * (
                    config.get("roll_step_deg", config["angular_step_deg"])
                    if i == 4
                    else config["linear_step_mm" if i < 3 else "angular_step_deg"]
                )
                for i, v in enumerate(values)
            ]
            scale = max(1, math.hypot(*values[:3]) / config["linear_step_mm"])
            for i in (3, 4):
                limit = (
                    config.get("roll_step_deg", config["angular_step_deg"])
                    if i == 4
                    else config["angular_step_deg"]
                )
                values[i] = max(-limit, min(limit, values[i]))
            result[group] = [v / scale if i < 3 else v for i, v in enumerate(values)]
        return result

    def cartesian_speed(self, command):
        config = self.controls.get("cartesian", {})
        if "rotation" in command and config.get("independent_rotation"):
            return {
                **command,
                "rotation_speed_deg_s": config["angular_speed_deg_s"] * self.roll_percent / 100,
            }
        return command

    def _choose(self, command, grip, now, *, step=False):
        moving = any(v for values in command.values() for v in values)
        gripping = any(grip.values())
        if not moving and not gripping:
            if self.continuous:
                self.continuous = False
                self.last_grip = {}
                return "release", {}
            return None
        if now - self.last_sent < 0.05 - 1e-9:
            return None
        changed_grip = grip != self.last_grip and (gripping or any(self.last_grip.values()))
        if changed_grip or (
            gripping and (not (moving or self.joint_active) or self.last_mode != "grip")
        ):
            mode, value = "grip", grip
            self.last_grip = dict(grip)
        else:
            mode = "cartesian" if self.mode == "mira-tool" else "step" if step else "jog"
            if self.mode == "joints" and self.controls.get("joint_velocity"):
                mode = "velocity"
            value = self._tool(command)
            self.last_jog = now
            self.joint_active = moving
        self.last_sent, self.last_mode = now, mode
        self.continuous = mode != "step"
        return mode, value

    def from_keyboard(self, now):
        self.keyboard.poll(now)
        keys = self.keyboard.active
        bindings = self.bindings()
        motion = [key for key in keys if key in bindings]
        self.stepped.intersection_update(motion)
        grip = {
            group: (int(pair[1] in keys) - int(pair[0] in keys)) * self.grip_speed
            for group in self.controls.get("grippers", [])
            if (pair := GRIP_KEYS.get(group))
        }
        command = self._empty()
        step = False
        if motion:
            if self.mode == "joints" and not self.controls.get("joint_velocity"):
                if not self.dual:
                    motion = motion[:1]
                fresh = [key for key in motion if key not in self.stepped]
                if fresh:
                    motion, step = fresh, True
                elif now - min(keys[key] for key in motion) < 0.45:
                    motion = []
            seconds = (
                0.05 if step or not math.isfinite(self.last_jog) else min(0.1, now - self.last_jog)
            )
            for key in motion:
                group, index, sign = bindings[key]
                command[group][index] += sign * (
                    1 if self.mode == "cartesian" else self.increment(index, seconds)
                )
        result = self._choose(command, grip, now, step=step)
        if result and result[0] == "step":
            self.stepped.update(motion)
        return result

    def from_gamepad(self, axes, buttons, state, now):
        axes = [deadzone(v) * (1 if i % 2 == 0 else -1) for i, v in enumerate(axes[:4])]

        def down(i):
            return int(i in buttons)

        cartesian = self.mode == "cartesian"
        roll = any(down(i) for i in ((12, 13, 14, 15) if cartesian else (12, 13, 0, 3)))
        grip = {}
        grip_pressed = False
        for group in self.controls.get("grippers", []):
            if group == "hand" and cartesian and not self.hold_grip:
                grip_pressed = bool(down(2))
            else:
                close, opened = (14, 15) if group == "left" else (2, 1)
                grip_pressed |= bool(down(close) or down(opened))
                grip[group] = (down(opened) - down(close)) * self.grip_speed
        neutral = not any(axes) and not roll and not grip_pressed
        pressed = not neutral or self.grip_target is not None if cartesian else down(4)
        alternate = not cartesian and bool(down(5))
        if alternate != self.alternate:
            if not (self.armed and not self.continuous and neutral):
                self.halt()
            self.alternate = alternate
        home = buttons & {9, 16} if self.controls.get("home_deg") else set()
        if home:
            button = next(iter(home))
            if (
                len(home) != 1
                or not neutral
                or pressed
                or self.continuous
                or self.home_button not in (None, button)
            ):
                self.halt()
                return "release", {}
            self.armed = False
            if self.home_ready:
                self.home_button = button
                self.home_since = now if self.home_since is None else self.home_since
                if now - self.home_since >= 1:
                    self.halt()
                    return "home", {}
            return None
        self.home_ready = True
        self.home_button = self.home_since = None
        if not grip_pressed:
            self.toggle_ready = True
        if not pressed:
            release = self.continuous
            self.armed = neutral
            self.continuous = False
            self.last_grip = {}
            self.last_jog = float("-inf")
            return ("release", {}) if release else None
        if not self.armed:
            return None
        if cartesian:
            position = state.get("grippers", {}).get("hand")
            if not self.hold_grip and grip_pressed and self.toggle_ready and position is not None:
                self.grip_target = (
                    0
                    if (self.grip_target if self.grip_target is not None else position) > 0.5
                    else 1
                )
                self.toggle_ready = False
            if self.grip_target is not None and position is not None:
                distance = self.grip_target - position
                if abs(distance) <= 0.015:
                    self.grip_target = None
                else:
                    grip["hand"] = math.copysign(self.grip_speed, distance)
            command = {
                "translation": [axes[1], -axes[0], axes[3]],
                "rotation": [down(14) - down(15), down(13) - down(12), -axes[2]],
            }
        else:
            command = self._empty()
            seconds = min(0.1, now - self.last_jog) if math.isfinite(self.last_jog) else 0.05
            if self.dual:
                for group, start in (("left", 0), ("right", 2)):
                    for i in range(2):
                        index = i + (2 if alternate else 0)
                        command[group][index] = axes[start + i] * self.increment(index, seconds)
                    if len(command[group]) > 4:
                        direction = down(12) - down(13) if group == "left" else down(3) - down(0)
                        command[group][4] = direction * self.increment(4, seconds)
            else:
                group = next(iter(command))
                for i, value in enumerate(axes):
                    index = i + (4 if alternate else 0)
                    if index < len(command[group]):
                        command[group][index] = value * self.increment(index, seconds)
        return self._choose(command, grip, now)
