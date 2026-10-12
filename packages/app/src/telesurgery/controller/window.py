# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Standalone desktop controls; rendering and input stay on Tk's main thread."""

import json
import signal
import sys
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import font, ttk

from telesurgery.controller.client import Client, Control
from telesurgery.controller.gamepad import Gamepads
from telesurgery.controller.input import GRIP_KEYS, Inputs
from telesurgery.controller.widgets import (
    BORDER,
    FONT,
    GREEN,
    INK,
    MUTED,
    Button,
    Slider,
    Tooltip,
    dropdown_style,
)


class Window:
    def __init__(self, root, client, robot=None, preferences=None, changed=None):
        self.root, self.client = root, client
        self.control = Control(client)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="robot-status")
        self.status_pending = None
        self.last_status = self.last_poll = self.last_devices = self.last_tick = 0
        self.last_feedback = 0
        self.session, self.robots = {}, {}
        self.selected, self.inputs = robot, None
        self.preferences = dict(preferences or {})
        self.changed = changed or (lambda _: None)
        self.initial_selection = robot is None
        self.robot_ids, self.device_ids = [], [None]
        self.gamepads = None
        self.gamepad_error = ""
        try:
            self.gamepads = Gamepads()
        except (OSError, RuntimeError) as exc:
            self.gamepad_error = str(exc)
        self.closing = self.pending_home = False
        self.pointer_control = False
        self.error = ""
        self.keys, self.sliders, self.positions, self.grippers = {}, [], {}, {}
        self.root.title("Robot control · Holoscan Telesurgery")
        self.root.geometry("420x750")
        self.root.minsize(400, 450)
        self.root.configure(bg="#f5f6f7")
        self.root.option_add("*Font", (FONT, 10))
        self.meter_font = font.Font(root, family=FONT, size=9)
        self.dropdown_images = dropdown_style(root)
        self.card = tk.Frame(
            root,
            bg="white",
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
        )
        self.card.pack(fill="both", expand=True, padx=12, pady=12)
        self.body = tk.Frame(self.card, bg="white")
        self.body.pack(fill="both", expand=True, padx=14, pady=12)
        self.label(self.body, "Robot control", size=13, bold=True).pack(anchor="w", pady=(0, 10))
        self.separator(self.body)
        self.robot_choice = ttk.Combobox(
            self.body, state="readonly", takefocus=False, font=(FONT, 10, "bold")
        )
        self.robot_choice.pack(fill="x", pady=(0, 10))
        self.robot_choice.bind("<<ComboboxSelected>>", self.select_robot)
        status_row = tk.Frame(self.body, bg="white")
        status_row.pack(fill="x", pady=(4, 8))
        self.status_dot = self.label(status_row, "●", color=MUTED, size=8)
        self.status_dot.pack(side="left", padx=(0, 5))
        self.status_label = self.label(status_row, "Connecting…", color=MUTED, size=9)
        self.status_label.pack(side="left")
        self.toolbar = tk.Frame(self.body, bg="white")
        self.toolbar.pack(fill="x", pady=(0, 10))
        self.device = ttk.Combobox(
            self.toolbar, state="readonly", values=["Keyboard"], takefocus=False, width=17
        )
        self.device.current(0)
        self.device.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.device.bind("<<ComboboxSelected>>", self.select_device)
        self.home = Button(self.toolbar, "Home", self.go_home, width=34, icon="home")
        self.home.pack(side="left", padx=(0, 8))
        Tooltip(self.home, "Home · Return to starting pose")
        self.stop_button = Button(self.toolbar, "Stop  Esc", self.stop, width=81, color="#a63735")
        self.stop_button.pack(side="left")
        Tooltip(self.stop_button, "Stop motion and release control · Esc")
        self.controls = tk.Frame(
            self.body,
            bg="#f6f8f7",
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        self.controls.pack(fill="both", expand=True)
        self.feedback_panel = tk.Frame(self.body, bg="white")
        self.feedback_panel.pack(fill="x", pady=(8, 0))
        self.message = self.label(self.body, "", size=9, color=MUTED)
        self.message.configure(wraplength=356)
        self.message.pack(anchor="w", fill="x", pady=(8, 0))
        root.bind("<KeyPress>", self.key_down)
        root.bind("<KeyRelease>", self.key_up)
        root.bind("<FocusOut>", lambda _: root.after_idle(self.check_focus))
        root.bind("<Unmap>", lambda event: self.stop() if event.widget == root else None)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(10, self.tick)

    @staticmethod
    def label(parent, text, *, size=10, color=INK, bold=False):
        return tk.Label(
            parent,
            text=text,
            bg="white",
            fg=color,
            font=(FONT, size, "bold" if bold else "normal"),
            anchor="w",
        )

    def stop(self):
        self.pending_home = False
        self.pointer_control = False
        if self.inputs:
            self.inputs.halt()
        self.control.stop()

    def focused(self):
        # Tk creates dropdown popups outside tkinter's widget registry.
        return bool(self.root.tk.call("focus", "-displayof", str(self.root)))

    def editing(self):
        try:
            focus = self.root.focus_get()
        except KeyError:
            return True  # A native dropdown's internal listbox owns focus.
        return isinstance(focus, (ttk.Combobox, Slider, tk.Entry))

    def check_focus(self):
        if not self.closing and not self.focused():
            self.stop()

    def permitted(self):
        robot = self.robots.get(self.selected, {})
        return (
            self.session.get("status") == "approved"
            and self.session.get("robot")
            and time.monotonic() - self.last_status < 2
            and robot.get("status") == "online"
            and not robot.get("stale")
            and not robot.get("error")
            and not robot.get("controls", {}).get("read_only")
            and (not robot.get("owner") or robot.get("owner_id") == self.session.get("id"))
        )

    def available(self):
        robot = self.robots.get(self.selected)
        state = self.control.feedback(robot) if robot else {}
        return (
            bool(self.permitted())
            and not state.get("home_active")
            and not state.get("stopping")
            and not self.pending_home
            and not self.closing
        )

    def select_robot(self, _=None):
        self.stop()
        index = self.robot_choice.current()
        if 0 <= index < len(self.robot_ids):
            self.selected = self.robot_ids[index]
            old_keys = self.inputs.keyboard if self.inputs else None
            self.inputs = Inputs(self.robots[self.selected])
            for kind in ("arm", "roll", "grip"):
                value = self.preferences.get(f"{self.selected}:{kind}-speed")
                if value is not None:
                    setattr(self.inputs, kind + "_percent", value)
            if old_keys:
                self.inputs.keyboard = old_keys
            self.build_controls()
            self.publish()
        self.root.focus_set()

    def select_device(self, _=None):
        self.stop()
        if self.gamepads:
            try:
                self.gamepads.select(self.device_ids[self.device.current()])
            except RuntimeError as exc:
                self.error = str(exc)
                self.device.current(0)
        self.build_controls()
        self.root.focus_set()

    def change_mode(self, _=None):
        self.stop()
        self.inputs.mode = self.mode_ids[self.mode_choice.current()]
        self.build_controls()
        self.root.focus_set()

    def speed_changed(self, kind, value):
        self.stop()
        setattr(self.inputs, kind + "_percent", value)
        self.preferences[f"{self.selected}:{kind}-speed"] = value
        self.publish()

    def publish(self):
        self.changed({"status": "running", "robot": self.selected, "preferences": self.preferences})

    def slider(self, parent, kind, text):
        limits = self.inputs.controls.get(
            "grip_speed_pct_s" if kind == "grip" else "speed_deg_s", {}
        )
        minimum = max(1, int(100 * limits.get("min", 0) / limits.get("max", 100) + 0.999))
        slider = Slider(
            parent,
            text,
            getattr(self.inputs, kind + "_percent"),
            lambda value: self.speed_changed(kind, value),
            minimum,
        )
        slider.pack(fill="x", pady=(0, 4))
        slider.bind("<ButtonRelease-1>", lambda _: self.root.focus_set())
        slider.bind("<Return>", lambda _: self.root.focus_set())
        slider.bind("<FocusIn>", lambda _: self.stop())
        self.sliders.append(slider)

    def cap(self, parent, key, *, width=34, text=None, shortcut=None):
        cap = Button(
            parent,
            text or key.upper(),
            width=width,
            hold=lambda down: self.pointer(key, down),
            shortcut=shortcut,
        )
        self.keys[key] = cap
        return cap

    def separator(self, parent):
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=10)

    def build_controls(self):
        for child in [*self.controls.winfo_children(), *self.feedback_panel.winfo_children()]:
            child.destroy()
        self.keys, self.sliders, self.positions, self.grippers = {}, [], {}, {}
        if not self.inputs:
            return
        inputs = self.inputs
        keyboard = self.device.current() == 0
        options = [("joints", "Individual joints (advanced)")]
        if inputs.controls.get("cartesian"):
            options.insert(0, ("cartesian", "Tool movement"))
        elif inputs.controls.get("mira_cartesian"):
            options = [("joints", "Joint movement"), ("mira-tool", "Tool movement · X/Y/Z + elbow")]
        self.mode_ids = [key for key, _ in options]
        self.mode_choice = ttk.Combobox(
            self.controls,
            style="Control.TCombobox",
            state="readonly",
            takefocus=False,
            values=[name for _, name in options],
        )
        self.mode_choice.current(self.mode_ids.index(inputs.mode))
        if len(options) > 1:
            self.mode_choice.pack(fill="x", pady=(0, 8))
        self.mode_choice.bind("<<ComboboxSelected>>", self.change_mode)
        self.slider(self.controls, "arm", "Arm speed")
        if keyboard and inputs.mode == "cartesian":
            grid = tk.Frame(self.controls, bg="white")
            grid.pack(fill="x")
            groups = [
                (
                    "Move",
                    [
                        ("w", "s", "Forward / back"),
                        ("a", "d", "Left / right"),
                        ("r", "f", "Up / down"),
                    ],
                ),
                (
                    "Rotate",
                    [
                        ("q", "e", "Turn"),
                        ("left", "right", "Side tilt"),
                        ("up", "down", "Forward tilt"),
                    ],
                ),
            ]
            symbols = {"left": "←", "right": "→", "up": "↑", "down": "↓"}
            for column, (title, rows) in enumerate(groups):
                section = tk.Frame(grid, bg="white")
                section.grid(
                    row=0, column=column, sticky="nsew", padx=(0, 10 if column == 0 else 0)
                )
                grid.columnconfigure(column, weight=1)
                self.label(section, title, size=9, color=MUTED, bold=True).grid(
                    row=0, column=0, columnspan=3, sticky="w", pady=(0, 4)
                )
                for row, (positive, negative, title) in enumerate(rows, 1):
                    self.cap(section, positive, text=symbols.get(positive)).grid(
                        row=row, column=0, pady=3
                    )
                    self.cap(section, negative, text=symbols.get(negative)).grid(
                        row=row, column=1, padx=(3, 5), pady=3
                    )
                    self.label(section, title, size=8).grid(row=row, column=2, sticky="w")
            self.label(
                self.controls,
                "Hold to move · release to stop                 Robot axes",
                size=8,
                color=MUTED,
            ).pack(anchor="w", pady=(6, 0))
        elif keyboard:
            grid = tk.Frame(self.controls, bg="white")
            grid.pack(fill="x")
            bindings = inputs.bindings()
            for column, (group, count) in enumerate(inputs.groups.items()):
                section = tk.Frame(grid, bg="white")
                section.grid(
                    row=0,
                    column=column,
                    sticky="nsew",
                    padx=(0, 10 if inputs.dual and column == 0 else 0),
                )
                grid.columnconfigure(column, weight=1)
                section.columnconfigure(1, weight=1)
                for col, title in enumerate(
                    [
                        group.title() if inputs.dual else "Joint",
                        "mm / °" if inputs.mode == "mira-tool" else "°",
                        "−",
                        "+",
                    ]
                ):
                    self.label(section, title, size=9, color=MUTED).grid(
                        row=0, column=col, sticky="e" if col == 1 else "w", padx=3
                    )
                for index in range(count):
                    title = "Roll" if inputs.dual and index == 4 else f"J{index + 1}"
                    if inputs.mode == "mira-tool":
                        title = inputs.controls["mira_cartesian"]["axes"][index]
                    self.label(section, title, size=9).grid(
                        row=index + 1, column=0, sticky="w", padx=(0, 5)
                    )
                    value = self.label(section, "—", size=9)
                    value.grid(row=index + 1, column=1, sticky="e", padx=(0, 8))
                    self.positions[group, index] = value
                    for col, sign in ((2, -1), (3, 1)):
                        key = next(
                            (k for k, b in bindings.items() if b == (group, index, sign)), None
                        )
                        if key:
                            self.cap(section, key, width=29 if inputs.dual else 34).grid(
                                row=index + 1, column=col, pady=2, padx=2
                            )
            if inputs.dual and inputs.groups.get("left") == 5:
                self.slider(self.controls, "roll", "Roll speed")
        else:
            self.gamepad_mapping()
        if inputs.controls.get("grippers"):
            self.separator(self.controls)
            self.slider(self.controls, "grip", "Grip speed")
            grip_grid = tk.Frame(self.controls, bg="white")
            grip_grid.pack(fill="x")
            for column, group in enumerate(inputs.controls["grippers"]):
                section = tk.Frame(grip_grid, bg="white")
                section.grid(row=0, column=column, sticky="ew", padx=(0, 8))
                grip_grid.columnconfigure(column, weight=1)
                if group != "hand":
                    self.label(section, group.title(), size=9, color=MUTED).pack(
                        anchor="w", pady=(0, 4)
                    )
                if group in GRIP_KEYS:
                    row = tk.Frame(section, bg="white")
                    row.pack(fill="x")
                    for key, text in zip(GRIP_KEYS[group], ("Close", "Open"), strict=True):
                        cap = self.cap(
                            row,
                            key,
                            width=78,
                            text=text,
                            shortcut=key.upper() if keyboard else None,
                        )
                        cap.pack(side="left", padx=(0, 4), fill="x", expand=True)
                        Tooltip(
                            cap,
                            (
                                f"Hold {key.upper()} or this button"
                                if keyboard
                                else "Hold this button"
                            )
                            + f" to {text.lower()} · Release to stop",
                        )
                meter = tk.Canvas(section, bg="white", height=18, highlightthickness=0, width=155)
                meter.pack(fill="x", pady=(4, 0))
                Tooltip(meter, "Measured opening · 0% closed · 100% open")
                self.grippers[group] = meter
        if not keyboard or inputs.mode == "cartesian":
            self.label(self.feedback_panel, "Measured joints (°)", bold=True, size=9).pack(
                anchor="w"
            )
            for group, count in inputs.groups.items():
                grid = tk.Frame(self.feedback_panel, bg="white")
                grid.pack(fill="x", pady=(4, 0))
                for index in range(count):
                    grid.columnconfigure(index, weight=1)
                    self.label(
                        grid,
                        "Roll" if inputs.dual and index == 4 else f"J{index + 1}",
                        size=8,
                        color=MUTED,
                    ).grid(row=0, column=index)
                    value = self.label(grid, "—", size=8)
                    value.grid(row=1, column=index)
                    self.positions[group, index] = value

        def background(widget):
            if "background" in widget.configure() and widget.cget("background") != BORDER:
                widget.configure(background="#f6f8f7")
            for child in widget.winfo_children():
                background(child)

        background(self.controls)
        self.root.after_idle(self.fit)

    def gamepad_mapping(self):
        tool = self.inputs.mode == "cartesian"
        self.label(
            self.controls,
            "Release controls to stop" if tool else "Hold LB / L1 to move",
            color=MUTED,
            size=9,
        ).pack(anchor="w", pady=(0, 8))
        if tool:
            rows = [
                ("Left stick", "Forward / back · left / right"),
                ("Right stick", "Up / down · turn"),
                ("D-pad", "Side tilt · forward tilt"),
                ("X / □", "Toggle gripper open / closed"),
            ]
        elif self.inputs.dual:
            first, second = (
                ("X / Y", "Z / elbow")
                if self.inputs.mode == "mira-tool"
                else ("J1 / J2", "J3 / J4")
            )
            rows = [
                ("Left / right stick", f"Left / right arm · {first}"),
                ("LB + RB / L1 + R1", f"{second} · move sticks"),
                ("D-pad ↑ / ↓", "Left tool roll"),
                ("Y / A · △ / ×", "Right tool roll"),
                ("D-pad ← / →", "Left gripper close / open"),
                ("X / B · □ / ○", "Right gripper close / open"),
            ]
        else:
            rows = [
                ("Left / right stick", "Joints 1–4"),
                ("LB + RB / L1 + R1", "Joints 5–8 · move sticks"),
            ]
        for title, description in rows:
            row = tk.Frame(self.controls, bg="white")
            row.pack(fill="x", pady=5)
            self.label(row, title, size=9, bold=True).pack(side="left")
            self.label(row, description, size=8, color=MUTED).pack(side="right")
        self.home_hint = self.label(
            self.controls, "Hold Guide or Start / Options for 1s to go Home", size=8, color=MUTED
        )
        self.home_hint.pack(anchor="w", pady=(10, 0))

    def fit(self):
        if not self.closing:
            self.root.update_idletasks()
            height = min(self.root.winfo_screenheight() - 90, self.body.winfo_reqheight() + 52)
            self.root.geometry(f"{max(420, self.root.winfo_width())}x{max(450, height)}")

    def pointer(self, key, down):
        if not self.inputs:
            return
        if down:
            allowed = self.available() and self.control.ready
            if allowed and self.device.current() != 0:
                self.stop()
                self.pointer_control = True
            self.inputs.keyboard.press(key, time.monotonic(), allowed)
        else:
            # Pointer release is unambiguous and does not need autorepeat coalescing.
            self.inputs.keyboard.active.pop(key, None)
            self.inputs.keyboard.down.discard(key)

    def key_down(self, event):
        key = ";" if event.keysym == "semicolon" else event.keysym.lower()
        if key == "escape":
            self.stop()
            self.root.focus_set()
            return "break"
        if not self.inputs:
            return
        bound = key in self.inputs.bindings() or any(
            key in GRIP_KEYS.get(g, "") for g in self.inputs.controls.get("grippers", [])
        )
        if bound:
            allowed = (
                self.available()
                and self.device.current() == 0
                and not self.editing()
                and not event.state & (0x4 | 0x8 | 0x20000)
                and not self.control.releasing
            )
            self.inputs.keyboard.press(key, time.monotonic(), allowed)
            return "break" if not self.editing() else None

    def key_up(self, event):
        if self.inputs:
            key = ";" if event.keysym == "semicolon" else event.keysym.lower()
            self.inputs.keyboard.release(key, time.monotonic())

    def go_home(self):
        robot = self.robots.get(self.selected)
        if not robot or not self.available() or self.control.feedback(robot).get("control_active"):
            return
        self.stop()
        self.pending_home = True
        self.root.focus_set()

    def update_status(self, status, now):
        self.last_status = now
        self.session = status.get("session", {}) if status.get("role") == "surgeon" else {}
        self.robots = {
            r["id"]: r
            for r in self.session.get("robots", [])
            if r.get("controls", {}).get("groups")
        }
        ids = list(self.robots)
        if ids != self.robot_ids:
            self.robot_ids = ids
            self.robot_choice["values"] = [
                self.robots[key]["name"]
                + (" · Simulation" if self.robots[key].get("simulation") else " · Physical")
                for key in ids
            ]
            if self.initial_selection and ids:
                self.selected = next(
                    (key for key in ids if self.robots[key]["status"] == "online"),
                    ids[0] if ids else None,
                )
                self.initial_selection = False
            if self.selected in ids:
                self.robot_choice.current(ids.index(self.selected))
                self.select_robot()
            else:
                self.stop()
                self.inputs = None
                self.robot_choice.set("Select a robot")
                self.build_controls()
        elif (
            self.inputs
            and self.selected in self.robots
            and self.inputs.controls != self.robots[self.selected]["controls"]
        ):
            self.select_robot()
        if status.get("role") != "surgeon":
            self.error = "Connect to a surgeon dashboard."

    def tick(self):
        now = time.monotonic()
        try:
            if self.last_tick and now - self.last_tick > 0.2:
                self.stop()
            self.last_tick = now
            self.control.poll(now)
            if self.control.failed:
                self.stop()
                self.control.failed = False
            if self.closing:
                if self.control.ready and not self.control.owned:
                    self.root.destroy()
                    return
            else:
                self.poll_status(now)
                self.poll_devices(now)
                self.drive(now)
                if now - self.last_feedback >= 0.05:
                    self.feedback()
                    self.last_feedback = now
        except Exception as exc:
            self.error = str(exc)
            self.stop()
        self.root.after(10, self.tick)

    def poll_status(self, now):
        if self.status_pending and self.status_pending.done():
            try:
                self.update_status(self.status_pending.result(), now)
                self.error = ""
            except Exception as exc:
                self.error = str(exc)
                self.last_status = 0
                self.stop()
            self.status_pending = None
        if self.status_pending is None and now - self.last_poll >= 0.25:
            self.status_pending = self.worker.submit(self.client.status)
            self.last_poll = now

    def poll_devices(self, now):
        if not self.gamepads or now - self.last_devices < 0.5:
            return
        self.last_devices = now
        devices = self.gamepads.devices()
        ids = [None, *devices]
        if ids == self.device_ids:
            return
        selected = self.gamepads.selected
        self.device_ids = ids
        self.device["values"] = [
            "Keyboard",
            *[f"{name} ({key})" for key, (_, name) in devices.items()],
        ]
        self.device.current(ids.index(selected) if selected in ids else 0)
        if selected not in ids:
            self.select_device()

    def drive(self, now):
        if self.inputs:
            self.inputs.keyboard.poll(now)
        if not self.permitted() or not self.focused() or self.editing():
            self.stop()
            return
        robot = self.robots.get(self.selected)
        if not robot or not self.inputs:
            return
        state = self.control.feedback(robot)
        if self.pending_home and self.control.ready and not state.get("stopping"):
            self.pending_home = False
            self.control.move(
                self.selected,
                "home",
                {},
                self.inputs.speed if self.inputs.controls.get("speed_deg_s") else None,
            )
            return
        if not self.available():
            self.inputs.halt()
            return
        if not self.control.ready:
            return
        if self.device.current() == 0 or self.pointer_control:
            request = self.inputs.from_keyboard(now)
            if self.pointer_control and not self.inputs.keyboard.down:
                self.pointer_control = False
                self.inputs.halt()
        else:
            sample = self.gamepads.sample() if self.gamepads else None
            if sample is None:
                self.stop()
                return
            request = self.inputs.from_gamepad(*sample, state, now)
        if request:
            mode, command = request
            if mode == "release":
                self.control.stop()
            elif mode == "home":
                self.go_home()
            else:
                self.control.move(
                    self.selected,
                    mode,
                    command,
                    self.inputs.speed if self.inputs.controls.get("speed_deg_s") else None,
                )

    def feedback(self):
        robot = self.robots.get(self.selected, {})
        state = self.control.feedback(robot) if robot else {}
        owned = self.control.owned == self.selected and not self.control.releasing
        status = (
            "Controlled by " + (self.session.get("name", "you") if owned else robot["owner"])
            if owned or robot.get("owner")
            else "Connected"
            if robot.get("status") == "online"
            else robot.get("status", self.session.get("status", "Disconnected")).title()
        )
        if state.get("home_active"):
            status += " · Going home…"
        elif state.get("stopping"):
            status += " · Stopping…"
        self.status_label.configure(text=status)
        self.status_dot.configure(
            fg=(
                GREEN
                if robot.get("status") == "online"
                and not robot.get("stale")
                and not robot.get("error")
                and not now_stale(self.last_status)
                else "#a63735"
                if robot.get("error")
                else MUTED
            )
        )
        available = self.available()
        self.home.update_state(
            available
            and not state.get("control_active")
            and bool(robot.get("controls", {}).get("home_deg"))
        )
        if self.inputs and self.device.current() != 0:
            remaining = (
                max(0, 1 - (time.monotonic() - self.inputs.home_since))
                if self.inputs.home_since is not None
                else None
            )
            self.home_hint.configure(
                text=(
                    f"Keep holding · Home in {remaining:.1f}s"
                    if remaining is not None
                    else "Hold Guide or Start / Options for 1s to go Home"
                )
            )
        self.mode_choice.configure(
            state="readonly" if available else "disabled"
        ) if self.inputs else None
        for key, cap in self.keys.items():
            cap.update_state(available, key in self.inputs.keyboard.active)
        for slider in self.sliders:
            slider.update_state(available)
        joints = state.get("joints_deg", state.get("targets_deg", {}))
        stale = robot.get("stale") or now_stale(self.last_status)
        for (group, index), label in self.positions.items():
            values = (
                state.get("cartesian_mm_deg", {}).get(group, [])
                if self.inputs.mode == "mira-tool" and index < 4
                else joints.get(group, [])
            )
            label.configure(
                text=f"{values[index]:.2f}" if index < len(values) and not stale else "—"
            )
        for group, meter in self.grippers.items():
            value = state.get("grippers", {}).get(group)
            meter.delete("all")
            width = meter.winfo_width()
            text = f"{value * 100:.0f}%" if value is not None and not stale else "—"
            end = max(2, width - self.meter_font.measure(text) - 7)
            meter.create_line(2, 9, end, 9, fill=BORDER, width=4, capstyle="round")
            if value is not None and not stale and value > 0:
                meter.create_line(
                    2,
                    9,
                    2 + (end - 2) * max(0, min(1, value)),
                    9,
                    fill=GREEN,
                    width=4,
                    capstyle="round",
                )
            meter.create_text(
                width - 1,
                9,
                anchor="e",
                text=text,
                font=self.meter_font,
                fill=MUTED,
            )
        self.message.configure(
            text=self.error
            or self.control.error
            or robot.get("error")
            or (
                "Focus this window to control the robot."
                if not self.focused()
                else "Center sticks and release buttons to resume."
                if self.device.current() != 0 and self.inputs and not self.inputs.armed
                else self.gamepad_error
            )
        )

    def close(self):
        self.stop()
        self.closing = True
        self.message.configure(text="Stopping and releasing control…")

    def shutdown(self):
        self.control.close()
        self.worker.shutdown(wait=True, cancel_futures=True)
        if self.gamepads:
            self.gamepads.close()


def now_stale(last_status):
    return time.monotonic() - last_status >= 2


def run(config):
    status_path = Path(config["status_path"]) if config.get("status_path") else None

    def report(value):
        if status_path:
            temporary = status_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({**value, "generation": config.get("generation")}))
            temporary.replace(status_path)

    window = None
    try:
        root = tk.Tk()
        window = Window(
            root,
            Client(config["server"], config.get("certificate")),
            config.get("robot"),
            config.get("preferences"),
            report,
        )
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: window.close())
        report({"status": "running"})
        root.mainloop()
    except Exception as exc:
        report({"status": "error", "error": str(exc)})
        raise
    finally:
        if window:
            window.shutdown()
    report({"status": "closed", "robot": window.selected, "preferences": window.preferences})


if __name__ == "__main__":
    run(json.loads(Path(sys.argv[1]).read_text()))
