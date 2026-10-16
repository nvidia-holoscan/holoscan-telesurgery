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
from telesurgery.controller.gamepad import (
    Gamepads,
    controller_bindings,
    controller_name,
    controller_selection,
)
from telesurgery.controller.haply import (
    DEFAULT_BASIS,
    Haply,
    MiraHaply,
    mapper_for,
    supports,
)
from telesurgery.controller.haply import NAME as HAPLY_NAME
from telesurgery.controller.haply import available as haply_available
from telesurgery.controller.input import GRIP_KEYS, Inputs
from telesurgery.controller.native_replay import NativeReplay, recording_for
from telesurgery.controller.widgets import (
    BORDER,
    FONT,
    GREEN,
    INK,
    MUTED,
    Badge,
    Button,
    Scale,
    Slider,
    ToolPosition,
    Tooltip,
    dropdown_style,
)

BASE_DIRECTIONS = (
    "Relative to this arm’s fixed base: forward +X, left +Y, up +Z. "
    "Camera and tool rotation do not change these directions."
)


class Window:
    def __init__(
        self,
        root,
        client,
        robot=None,
        preferences=None,
        changed=None,
        input_device=None,
        retain_control=False,
    ):
        self.root, self.client = root, client
        self.px = Scale(root)
        self.control = Control(client)
        self.replay = NativeReplay(client, self.control)
        self.recordings = []
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="robot-status")
        self.status_pending = None
        self.last_status = self.last_poll = self.last_devices = self.last_tick = 0
        self.last_feedback = 0
        self.session, self.robots = {}, {}
        self.selected, self.inputs = robot, None
        self.replay_manual_mode = None
        self.switching_robot = False
        self.pending_robot = None
        self.incoming_control = robot if retain_control else None
        self.return_control = False
        self.returning_robot = None
        self.handed_off = None
        self.preferences = dict(preferences or {})
        self.restore_input = input_device
        self.changed = changed or (lambda _: None)
        self.initial_selection = robot is None
        self.robot_ids, self.device_ids = [], [None]
        self.gamepads = None
        self.gamepad_error = ""
        self.haply = None
        self.haply_input = MiraHaply()
        self.haply_error = ""
        try:
            self.gamepads = Gamepads()
        except (OSError, RuntimeError) as exc:
            self.gamepad_error = str(exc)
        self.closing = self.pending_home = False
        self.pending_reset = False
        self.pointer_control = False
        self.gamepad_sample = None
        self.error = ""
        self.keys, self.sliders, self.positions, self.grippers = {}, [], {}, {}
        self.root.title("Robot control · Holoscan Telesurgery")
        self.root.geometry(f"{self.px(420)}x{self.px(750)}")
        self.root.minsize(self.px(400), self.px(450))
        self.root.configure(bg="#f5f6f7")
        self.root.option_add("*Font", (FONT, 10))
        self.meter_font = font.Font(root, family=FONT, size=9)
        self.dropdown_images = dropdown_style(root)
        self.card = tk.Frame(
            root,
            bg="white",
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=self.px(1),
        )
        self.card.pack(fill="both", expand=True, padx=self.px(12), pady=self.px(12))
        self.body = tk.Frame(self.card, bg="white")
        self.body.pack(fill="both", expand=True, padx=self.px(14), pady=self.px(12))
        self.label(self.body, "Robot control", size=13, bold=True).pack(
            anchor="w", pady=self.px(0, 10)
        )
        self.separator(self.body)
        self.robot_choice = ttk.Combobox(
            self.body,
            state="disabled" if self.incoming_control else "readonly",
            takefocus=False,
            font=(FONT, 10, "bold"),
        )
        self.robot_choice.pack(fill="x", pady=self.px(0, 10))
        self.robot_choice.bind("<<ComboboxSelected>>", self.select_robot)
        status_row = tk.Frame(self.body, bg="white")
        status_row.pack(fill="x", pady=self.px(4, 8))
        self.status_dot = self.label(status_row, "●", color=MUTED, size=8)
        self.status_dot.pack(side="left", padx=self.px(0, 5))
        self.status_label = self.label(status_row, "Connecting…", color=MUTED, size=9)
        self.status_label.configure(wraplength=self.px(240))
        self.status_label.pack(side="left", fill="x", expand=True)
        self.acquire_button = Button(status_row, "Acquire", self.acquire_control, width=72)
        Tooltip(self.acquire_button, "Acquire control")
        self.release_button = Button(
            status_row, "Release control", self.release_control, width=34, icon="release"
        )
        Tooltip(self.release_button, "Release control")
        self.toolbar = tk.Frame(self.body, bg="white")
        self.toolbar.pack(fill="x", pady=self.px(0, 10))
        self.device = ttk.Combobox(
            self.toolbar,
            state="readonly",
            values=["Keyboard"],
            takefocus=False,
            width=17,
            font=(FONT, 10, "bold"),
        )
        self.device.current(0)
        self.device.pack(side="left", fill="x", expand=True, padx=self.px(0, 8))
        self.device.bind("<<ComboboxSelected>>", self.select_device)
        self.home = Button(self.toolbar, "Home", self.go_home, width=34, icon="home")
        self.home.pack(side="left", padx=self.px(0, 8))
        Tooltip(self.home, "Home · Return to starting pose")
        self.reset_button = Button(
            self.toolbar, "Reset scene", self.reset_scene, width=34, icon="reset"
        )
        Tooltip(self.reset_button, "Reset scene")
        self.replay_button = Button(
            self.toolbar, "Replay inputs", self.start_replay, width=34, icon="replay"
        )
        Tooltip(self.replay_button, "Replay inputs")
        self.stop_button = Button(
            self.toolbar, "Stop", self.stop, width=34, color="#a63735", icon="stop"
        )
        self.stop_button.pack(side="left")
        Tooltip(self.stop_button, "Stop motion · Esc")
        self.replay_status = self.label(self.body, "", size=9, color=MUTED)
        self.replay_status.configure(wraplength=self.px(356))
        self.controls = tk.Frame(
            self.body,
            bg="#f6f8f7",
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=self.px(1),
            padx=self.px(10),
            pady=self.px(10),
        )
        self.controls.pack(fill="both", expand=True)
        self.feedback_panel = tk.Frame(self.body, bg="white")
        self.feedback_panel.pack(fill="x", pady=self.px(8, 0))
        self.message = self.label(self.body, "", size=9, color=MUTED)
        self.message.configure(wraplength=self.px(356))
        self.message.pack(anchor="w", fill="x", pady=self.px(8, 0))
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

    def stop(self, reason="operator stopped replay"):
        self.replay.stop(reason)
        self.sync_replay_mode()
        self.pending_home = False
        self.pending_reset = False
        self.pointer_control = False
        self.gamepad_sample = None
        self.haply_input.halt(
            self.haply_input.error
            if self.haply_input.paused
            else "Movement stopped; tap Start to resume."
            if reason == "operator stopped replay"
            else f"{reason}; tap Start to resume."
        )
        if self.inputs:
            self.inputs.halt()
        self.control.stop()

    def acquire_control(self):
        self.stop()
        if not self.switching_robot and self.eligible():
            self.control.acquire(self.selected)

    def release_control(self):
        self.stop()
        robot = self.robots.get(self.selected, {})
        mine = bool(self.session.get("id") and robot.get("owner_id") == self.session["id"])
        self.control.release(self.selected if mine else None)

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
        if (
            not self.closing
            and not self.focused()
            and not (self.replay.active and self.root.winfo_viewable())
        ):
            self.stop()

    def eligible(self):
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

    def permitted(self):
        return (
            not self.switching_robot
            and self.eligible()
            and self.control.owned == self.selected
            and not self.control.releasing
        )

    def available(self):
        robot = self.robots.get(self.selected)
        state = self.control.feedback(robot) if robot else {}
        return (
            bool(self.permitted())
            and not state.get("home_active")
            and not state.get("stopping")
            and not self.pending_home
            and not self.pending_reset
            and not self.replay.busy
            and not self.closing
        )

    def select_robot(self, _=None):
        if self.switching_robot:
            return
        index = self.robot_choice.current()
        if not 0 <= index < len(self.robot_ids):
            return
        selected = self.robot_ids[index]
        self.stop("Robot selection changed")
        if selected != self.selected and (self.control.owned or self.control.release_failed):
            self.switching_robot = True
            self.robot_choice.configure(state="disabled")
            if self.selected in self.robot_ids:
                self.robot_choice.current(self.robot_ids.index(self.selected))
            else:
                self.robot_choice.set("Select a robot")
            confirmed = self.confirm_robot_switch(selected)
            if self.closing:
                return
            if confirmed:
                self.pending_robot = selected
                self.control.release()
                return
            self.switching_robot = False
            self.robot_choice.configure(state="readonly")
        else:
            self.apply_robot_selection(selected)
        self.root.focus_set()

    def confirm_robot_switch(self, selected):
        dialog = tk.Toplevel(self.root)
        dialog.title("Release control and switch?")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg="white", padx=self.px(20), pady=self.px(18))
        accepted = False

        def finish(confirm=False):
            nonlocal accepted
            accepted = confirm
            dialog.destroy()

        self.label(dialog, "Release control and switch?", size=12, bold=True).pack(anchor="w")
        name = self.robots[selected]["name"]
        description = self.label(
            dialog,
            f"Release the current robot before selecting {name}.\n\n"
            "Acquire control of the new robot when you are ready.",
        )
        description.configure(wraplength=self.px(360), justify="left")
        description.pack(fill="x", pady=self.px(12, 18))
        actions = tk.Frame(dialog, bg="white")
        actions.pack(fill="x")
        cancel = ttk.Button(actions, text="Cancel", command=finish)
        cancel.pack(side="left")
        ttk.Button(actions, text="Release control and switch", command=lambda: finish(True)).pack(
            side="right", padx=self.px(12, 0)
        )
        dialog.protocol("WM_DELETE_WINDOW", finish)
        dialog.bind("<Escape>", lambda _: finish())
        dialog.update_idletasks()
        dialog.geometry(
            f"+{self.root.winfo_rootx() + self.px(20)}+{self.root.winfo_rooty() + self.px(80)}"
        )
        dialog.grab_set()
        cancel.focus_set()
        self.root.wait_window(dialog)
        return accepted and not self.closing

    def finish_robot_switch(self):
        if (
            self.closing
            or self.pending_robot is None
            or self.control.pending
            or self.control.releasing
        ):
            return
        selected, self.pending_robot = self.pending_robot, None
        self.switching_robot = False
        self.robot_choice.configure(state="readonly")
        if not self.control.release_failed and not self.control.owned:
            self.apply_robot_selection(selected)
        self.root.focus_set()

    def apply_robot_selection(self, selected):
        if selected in self.robot_ids:
            self.selected = selected
            self.robot_choice.current(self.robot_ids.index(selected))
            if self.device.get() == HAPLY_NAME and not self.haply_supported():
                self.device.current(0)
                self.select_device()
            old_keys = self.inputs.keyboard if self.inputs else None
            self.inputs = Inputs(self.robots[self.selected])
            self.haply_input = mapper_for(self.robots[self.selected])
            for kind in ("arm", "roll", "grip"):
                value = self.preferences.get(f"{self.selected}:{kind}-speed")
                if value is not None:
                    setattr(self.inputs, kind + "_percent", value)
            if old_keys:
                self.inputs.keyboard = old_keys
            self.build_controls()
            self.publish()

    def select_device(self, _=None):
        self.stop()
        haply = self.device.get() == HAPLY_NAME and self.haply_supported()
        if self.haply and not haply:
            self.haply.close()
            self.haply = None
        if haply:
            self.haply_input = mapper_for(self.robots[self.selected])
        if haply and self.haply is None:
            self.haply = Haply()
        if self.gamepads:
            try:
                self.gamepads.select(None if haply else self.device_ids[self.device.current()])
            except RuntimeError as exc:
                self.error = str(exc)
                self.device.current(0)
        self.build_controls()
        self.publish()
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
        self.changed(self.window_state("running"))

    def window_state(self, status):
        selection = (
            controller_selection(self.gamepads.devices(), self.gamepads.selected)
            if self.gamepads
            else None
        )
        if self.haply:
            selection = {"name": HAPLY_NAME, "ordinal": 0, "count": 1}
        return {
            "status": status,
            "robot": self.selected,
            "acquired": self.control.owned if not self.incoming_control else None,
            "handoff": self.handed_off if status == "closed" else None,
            "handoff_error": (
                self.control.error or "Control could not be returned to the dashboard."
                if status == "closed" and self.returning_robot and not self.handed_off
                else ""
            ),
            "preferences": self.preferences,
            "input": selection,
        }

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
        slider.pack(fill="x", pady=self.px(0, 4))
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
        tk.Frame(parent, bg=BORDER, height=self.px(1)).pack(fill="x", pady=self.px(10))

    def build_controls(self):
        for child in [*self.controls.winfo_children(), *self.feedback_panel.winfo_children()]:
            child.destroy()
        self.keys, self.sliders, self.positions, self.grippers = {}, [], {}, {}
        if not self.inputs:
            return
        self.gamepad_badges, self.gamepad_keys = [], {}
        self.gamepad_status = None
        self.home.tooltip.text = "Home · Return to starting pose"
        inputs = self.inputs
        keyboard = self.device.current() == 0
        haply = self.device.get() == HAPLY_NAME
        hold_gamepad_grip = inputs.dual or inputs.hold_grip or inputs.mode != "cartesian"
        buttons = controller_bindings(self.device.get())
        grip_keys = {"z": "←", "x": "→", "n": buttons["close"], "m": buttons["open"]}
        if not inputs.dual:
            grip_keys.update(z=buttons["close"], x=buttons["open"])
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
        if len(options) > 1 and not haply:
            self.mode_choice.pack(fill="x", pady=self.px(0, 8))
        self.mode_choice.bind("<<ComboboxSelected>>", self.change_mode)
        if keyboard or haply:
            self.message.pack(anchor="w", fill="x", pady=self.px(8, 0))
            self.slider(self.controls, "arm", "Arm speed")
        else:
            self.message.pack_forget()
        if haply:
            self.haply_mapping()
        elif keyboard and inputs.mode == "cartesian":
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
                    row=0, column=column, sticky="nsew", padx=self.px(0, 10 if column == 0 else 0)
                )
                grid.columnconfigure(column, weight=1)
                self.label(section, title, size=9, color=MUTED, bold=True).grid(
                    row=0, column=0, columnspan=3, sticky="w", pady=self.px(0, 4)
                )
                for row, (positive, negative, title) in enumerate(rows, 1):
                    self.cap(section, positive, text=symbols.get(positive)).grid(
                        row=row, column=0, pady=self.px(3)
                    )
                    self.cap(section, negative, text=symbols.get(negative)).grid(
                        row=row, column=1, padx=self.px(3, 5), pady=self.px(3)
                    )
                    self.label(section, title, size=8).grid(row=row, column=2, sticky="w")
            hint = self.label(
                self.controls,
                "Hold to move · release to stop          Arm-base directions",
                size=8,
                color=MUTED,
            )
            hint.pack(anchor="w", pady=self.px(6, 0))
            Tooltip(hint, BASE_DIRECTIONS)
            if inputs.controls.get("cartesian", {}).get("independent_rotation"):
                self.slider(self.controls, "roll", "Rotation speed")
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
                    padx=self.px(0, 10 if inputs.dual and column == 0 else 0),
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
                        row=0, column=col, sticky="e" if col == 1 else "w", padx=self.px(3)
                    )
                for index in range(count):
                    title = "Roll" if inputs.dual and index == 4 else f"J{index + 1}"
                    if inputs.mode == "mira-tool":
                        title = inputs.controls["mira_cartesian"]["axes"][index]
                    self.label(section, title, size=9).grid(
                        row=index + 1, column=0, sticky="w", padx=self.px(0, 5)
                    )
                    value = self.label(section, "—", size=9)
                    value.grid(row=index + 1, column=1, sticky="e", padx=self.px(0, 8))
                    self.positions[group, index] = value
                    for col, sign in ((2, -1), (3, 1)):
                        key = next(
                            (k for k, b in bindings.items() if b == (group, index, sign)), None
                        )
                        if key:
                            self.cap(section, key, width=29 if inputs.dual else 34).grid(
                                row=index + 1, column=col, pady=self.px(2), padx=self.px(2)
                            )
            if inputs.dual and inputs.groups.get("left") == 5:
                self.slider(self.controls, "roll", "Rotation speed")
        else:
            self.gamepad_mapping()
        if inputs.controls.get("grippers"):
            self.separator(self.controls)
            self.slider(self.controls, "grip", "Grip speed")
            if haply:
                for text in (
                    "Hold single-dot button · Close gripper",
                    "Hold two-dot button · Open gripper",
                ):
                    self.label(self.controls, text, size=9).pack(anchor="w", pady=self.px(3))
            if (
                not keyboard
                and not inputs.hold_grip
                and inputs.mode == "cartesian"
                and "hand" in inputs.controls["grippers"]
            ):
                row = tk.Frame(self.controls, bg="white")
                row.pack(fill="x", pady=self.px(0, 6))
                self.badge(row, buttons["close"], ("button", 2)).pack(
                    side="left", padx=self.px(0, 8)
                )
                self.label(row, "Open / close", size=8).pack(side="left")
            grip_grid = tk.Frame(self.controls, bg="white")
            grip_grid.pack(fill="x")
            for column, group in enumerate(inputs.controls["grippers"]):
                section = tk.Frame(grip_grid, bg="white")
                section.grid(row=0, column=column, sticky="ew", padx=self.px(0, 8))
                grip_grid.columnconfigure(column, weight=1)
                if group != "hand":
                    self.label(section, group.title(), size=9, color=MUTED).pack(
                        anchor="w", pady=self.px(0, 4)
                    )
                if group in GRIP_KEYS and not haply:
                    row = tk.Frame(section, bg="white")
                    row.pack(fill="x")
                    for key, text in zip(GRIP_KEYS[group], ("Close", "Open"), strict=True):
                        cap = self.cap(
                            row,
                            key,
                            width=78,
                            text=text,
                            shortcut=key.upper()
                            if keyboard
                            else (grip_keys[key] if hold_gamepad_grip and not haply else None),
                        )
                        cap.pack(side="left", padx=self.px(0, 4), fill="x", expand=True)
                        if not keyboard and not haply and hold_gamepad_grip:
                            pair = (14, 15) if group == "left" else (2, 1)
                            self.gamepad_keys[key] = pair if text == "Close" else pair[::-1]
                        Tooltip(
                            cap,
                            (
                                f"Hold {key.upper()} or this button"
                                if keyboard
                                else "Hold this button"
                                if haply
                                else f"Hold {grip_keys[key]} or this button"
                                if hold_gamepad_grip and inputs.mode == "cartesian"
                                else f"Hold {buttons['enable']} + {grip_keys[key]} or this button"
                                if hold_gamepad_grip
                                else "Hold this button"
                            )
                            + f" to {text.lower()} · Release to stop",
                        )
                meter = tk.Canvas(
                    section,
                    bg="white",
                    height=self.px(18),
                    highlightthickness=0,
                    width=self.px(155),
                )
                meter.pack(fill="x", pady=self.px(4, 0))
                Tooltip(meter, "Measured opening · 0% closed · 100% open")
                self.grippers[group] = meter
        if not keyboard or inputs.mode == "cartesian":
            self.label(self.feedback_panel, "Measured joints (°)", bold=True, size=9).pack(
                anchor="w"
            )
            if inputs.dual:
                grid = tk.Frame(self.feedback_panel, bg="white")
                grid.pack(fill="x", pady=self.px(4, 0))
                for index in range(inputs.groups["left"]):
                    grid.columnconfigure(index + 1, weight=1)
                    self.label(
                        grid, "Roll" if index == 4 else f"J{index + 1}", size=8, color=MUTED
                    ).grid(row=0, column=index + 1)
                for row, (group, count) in enumerate(inputs.groups.items(), 1):
                    self.label(grid, group.title(), size=8, color=MUTED).grid(
                        row=row, column=0, sticky="w"
                    )
                    for index in range(count):
                        value = self.label(grid, "—", size=8)
                        value.grid(row=row, column=index + 1)
                        self.positions[group, index] = value
            else:
                for group, count in inputs.groups.items():
                    grid = tk.Frame(self.feedback_panel, bg="white")
                    grid.pack(fill="x", pady=self.px(4, 0))
                    for index in range(count):
                        grid.columnconfigure(index, weight=1)
                        self.label(grid, f"J{index + 1}", size=8, color=MUTED).grid(
                            row=0, column=index
                        )
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

    def badge(self, parent, text, binding):
        cap = Badge(parent, text)
        self.gamepad_badges.append((cap, binding))
        return cap

    def haply_supported(self):
        robot = getattr(self, "robots", {}).get(getattr(self, "selected", None), {})
        return supports(robot)

    def haply_mapping(self):
        self.haply_status = self.label(
            self.controls, "Paused · Left arm" if self.inputs.dual else "Paused", bold=True
        )
        self.haply_status.pack(anchor="w", pady=self.px(4, 8))
        config = self.inputs.controls.get("mira_cartesian") or self.inputs.controls["cartesian"]
        self.haply_position = ToolPosition(
            self.controls, config.get("input_basis", config.get("haply_basis", DEFAULT_BASIS))
        )
        self.haply_position.pack(fill="x", pady=self.px(0, 8))
        self.range_button = ttk.Button(
            self.controls, text="Calibrate movement range", command=self.calibrate_haply
        )
        self.range_button.pack(anchor="w", pady=self.px(4))
        self.range_cancel = ttk.Button(
            self.controls,
            text="Cancel range calibration",
            command=lambda: self.calibrate_haply("cancel"),
        )
        self.range_hint = self.label(self.controls, "", size=9)
        self.range_hint.configure(wraplength=self.px(340))
        self.range_hint.pack(anchor="w", fill="x")
        for text in (
            "Tap single-dot button · Start / stop movement",
            *(("Tap two-dot button · Switch left / right arm",) if self.inputs.dual else ()),
            "Move pen · Move tool",
            "Tilt pen up / down · Angle tool" if self.inputs.dual else "Tilt pen · Angle tool",
        ):
            self.label(self.controls, text, size=9).pack(anchor="w", pady=self.px(3))
        self.separator(self.controls)
        self.slider(self.controls, "roll", "Rotation speed")
        self.label(self.controls, "Twist pen · Roll tool", size=9).pack(anchor="w", pady=self.px(3))

    def calibrate_haply(self, action=None):
        self.stop()
        sample, error = self.haply.sample(time.monotonic())
        try:
            self.haply_input.calibrate(
                action or ("save" if self.haply_input.calibration.collecting else "start"), sample
            )
            self.error = ""
        except (OSError, ValueError) as exc:
            self.error = error or str(exc)
        self.root.focus_set()

    def gamepad_mapping(self):
        inputs = self.inputs
        tool = inputs.mode == "cartesian"
        buttons = controller_bindings(self.device.get())
        roll = inputs.dual and inputs.groups.get("left") == 5
        tools = (
            "arms, roll & grip"
            if roll and inputs.controls.get("grippers")
            else "arms & roll"
            if roll
            else "movement"
        )
        self.gamepad_guidance = (
            "Release controls to stop" if tool else f"Hold {buttons['enable']} for {tools}"
        )
        self.gamepad_status = self.label(self.controls, self.gamepad_guidance, color=MUTED, size=8)
        self.gamepad_status.configure(width=1)
        self.gamepad_status.pack(fill="x", pady=self.px(0, 8))
        Tooltip(self.gamepad_status, self.gamepad_guidance)
        self.slider(self.controls, "arm", "Arm speed")
        grid = tk.Frame(self.controls, bg="white")
        grid.pack(fill="x")
        if tool:
            for column in range(2):
                grid.columnconfigure(column, weight=1, uniform="directions")
            for index, (title, rows) in enumerate(
                [
                    (
                        "Left stick",
                        [("↔", "Left / right", ("axis", 0)), ("↕", "Forward / back", ("axis", 1))],
                    ),
                    ("Right stick", [("↕", "Up / down", ("axis", 3)), ("↔", "Turn", ("axis", 2))]),
                    (
                        "D-pad · tilt",
                        [
                            ("↔", "Side to side", ("pair", 14, 15)),
                            ("↕", "Forward / back", ("pair", 12, 13)),
                        ],
                    ),
                ]
            ):
                section = tk.Frame(grid, bg="white")
                section.grid(
                    row=index // 2,
                    column=index % 2,
                    sticky="nsew",
                    padx=self.px(0, 8 if index % 2 == 0 else 0),
                    pady=self.px(6, 0),
                )
                self.label(section, title, size=8, color=MUTED).pack(anchor="w", pady=self.px(0, 3))
                for glyph, title, binding in rows:
                    row = tk.Frame(section, bg="white")
                    row.pack(fill="x", pady=self.px(2))
                    self.badge(row, glyph, binding).pack(side="left", padx=self.px(0, 6))
                    self.label(row, title, size=8).pack(side="left")
            hint = self.label(grid, "Arm-base directions", size=8, color=MUTED)
            hint.grid(row=1, column=1, sticky="se", pady=self.px(2))
            Tooltip(hint, BASE_DIRECTIONS)
            if inputs.controls.get("cartesian", {}).get("independent_rotation"):
                self.slider(self.controls, "roll", "Rotation speed")
        else:
            first, second = (
                ("X / Y", "Z / elbow")
                if inputs.mode == "mira-tool"
                else ("Joints 1–2", "Joints 3–4")
                if inputs.dual
                else ("Joints 1–4", f"Joints 5–{sum(inputs.groups.values())}")
            )
            for index, (key, title) in enumerate(
                [
                    (buttons["enable"], first),
                    (f"{buttons['enable']} + {buttons['alternate']}", second),
                ]
            ):
                section = tk.Frame(grid, bg="white")
                section.pack(fill="x", pady=self.px(3, 6))
                heading = tk.Frame(section, bg="white")
                heading.pack(fill="x")
                self.badge(heading, key, ("bank", index)).pack(side="left", padx=self.px(0, 8))
                self.label(heading, title, size=8).pack(side="left")
                sticks = tk.Frame(section, bg="white")
                sticks.pack(fill="x", pady=self.px(4, 0))
                for stick in range(2):
                    column = tk.Frame(sticks, bg="white")
                    column.grid(row=0, column=stick, sticky="nw")
                    sticks.columnconfigure(stick, weight=1, uniform="sticks")
                    self.label(
                        column, "Left stick" if stick == 0 else "Right stick", size=8, color=MUTED
                    ).pack(anchor="w")
                    for direction in range(2):
                        axis = stick * 2 + direction
                        joint = index * 2 + direction if inputs.dual else index * 4 + axis
                        group = ("right" if stick else "left") if inputs.dual else "joints"
                        if joint >= inputs.groups[group]:
                            continue
                        label = (
                            inputs.controls["mira_cartesian"]["axes"][joint]
                            if inputs.mode == "mira-tool"
                            else f"J{joint + 1}"
                        )
                        row = tk.Frame(column, bg="white")
                        row.pack(fill="x", pady=self.px(2))
                        self.badge(row, "↕" if direction else "↔", ("bank_axis", index, axis)).pack(
                            side="left", padx=self.px(0, 6)
                        )
                        self.label(row, label, size=8).pack(side="left")
        if roll:
            self.separator(self.controls)
            self.slider(self.controls, "roll", "Rotation speed")
            grid = tk.Frame(self.controls, bg="white")
            grid.pack(fill="x")
            for column, (title, keys) in enumerate(
                [
                    ("Left", [("↑", 12, 13), ("↓", 13, 12)]),
                    ("Right", [(buttons["roll_up"], 3, 0), (buttons["roll_down"], 0, 3)]),
                ]
            ):
                section = tk.Frame(grid, bg="white")
                section.grid(row=0, column=column, sticky="ew")
                grid.columnconfigure(column, weight=1, uniform="roll")
                self.label(section, title, size=8, color=MUTED).pack(anchor="w", pady=self.px(0, 4))
                row = tk.Frame(section, bg="white")
                row.pack(fill="x")
                for glyph, positive, negative in keys:
                    self.badge(row, glyph, ("button", positive, negative)).pack(
                        side="left", padx=self.px(0, 6)
                    )
        self.home_instruction = (
            f"Home · Hold {buttons['home']} or {buttons['home_fallback']} for 1s"
        )
        self.home.tooltip.text = self.home_instruction

    def gamepad_active(self, binding):
        kind, *values = binding
        if self.replay.active:
            replay = self.replay.input or {}
            if replay.get("device") != "gamepad":
                return False
            axes, buttons = replay["axes"], replay["buttons"]
            if "banks" in replay and kind in {"bank", "bank_axis"}:
                bank = replay["banks"][values[0]]
                if kind == "bank":
                    return any(bank) or (values[0] == 0 and 4 in buttons and 5 not in buttons)
                return bank[values[1]] != 0
        else:
            if not self.gamepad_sample or not self.inputs.armed or self.pointer_control:
                return False
            axes, buttons = self.gamepad_sample
        if kind == "axis":
            return abs(axes[values[0]]) > 0.15
        if kind == "bank":
            return 4 in buttons and int(5 in buttons) == values[0]
        if kind == "bank_axis":
            return 4 in buttons and int(5 in buttons) == values[0] and abs(axes[values[1]]) > 0.15
        if kind == "pair":
            return (values[0] in buttons) != (values[1] in buttons)
        return values[0] in buttons and (len(values) == 1 or values[1] not in buttons)

    def fit(self):
        if not self.closing:
            self.root.update_idletasks()
            width = max(self.px(420), self.root.winfo_reqwidth())
            height = min(
                self.root.winfo_screenheight() - self.px(90),
                max(self.px(450), self.root.winfo_reqheight()),
            )
            self.root.minsize(width, height)
            self.root.geometry(f"{max(width, self.root.winfo_width())}x{height}")

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

    def reset_scene(self):
        robot = self.robots.get(self.selected)
        if (
            not robot
            or not self.permitted()
            or not robot.get("simulation")
            or not robot["controls"].get("reset_scene")
            or robot.get("reset_scene_blocked")
        ):
            return
        self.stop()
        self.pending_reset = True
        self.root.focus_set()

    def replay_recording(self):
        device = (
            "haply"
            if self.device.get() == HAPLY_NAME
            else "keyboard"
            if self.device.current() == 0
            else "gamepad"
        )
        return recording_for(self.recordings, self.robots.get(self.selected, {}), device)

    def start_replay(self):
        recording = self.replay_recording()
        if not recording or not self.available() or self.replay.busy:
            return
        self.stop()
        self.replay.start(self.robots[self.selected], recording)
        self.root.focus_set()

    def sync_replay_mode(self):
        if self.replay.active and self.inputs:
            mode = (self.replay.input or {}).get("mode")
            if not mode or mode == self.inputs.mode:
                return
            if self.replay_manual_mode is None:
                self.replay_manual_mode = self.inputs, self.inputs.mode
        elif self.replay_manual_mode:
            inputs, mode = self.replay_manual_mode
            self.replay_manual_mode = None
            if inputs is not self.inputs:
                return
        else:
            return
        self.inputs.mode = mode
        self.build_controls()

    def update_status(self, status, now):
        self.last_status = now
        self.recordings = status.get("replays", [])
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
        if self.incoming_control and not self.control.owned and self.eligible():
            self.control.adopt(self.incoming_control)

    def tick(self):
        now = time.monotonic()
        try:
            if self.last_tick and now - self.last_tick > 0.2:
                self.stop("controller timer delayed")
            self.last_tick = now
            self.control.poll(now)
            if self.control.failed:
                self.stop(self.control.error or "robot input failed")
                self.control.failed = False
            if self.incoming_control and self.control.ready and self.control.owned:
                self.incoming_control = None
                self.robot_choice.configure(state="readonly")
                self.publish()
            self.finish_robot_switch()
            if self.closing:
                if (
                    self.control.pending is None
                    and (not self.control.owned or (self.return_control and self.control.ready))
                    and not self.replay.busy
                ):
                    if self.return_control:
                        self.handed_off, self.control.owned = self.control.owned, None
                    self.root.destroy()
                    return
            else:
                self.poll_status(now)
                self.poll_devices(now)
                self.drive(now)
                if now - self.last_feedback >= 0.05:
                    self.feedback()
                    self.last_feedback = now
            self.replay.poll(now)
            self.sync_replay_mode()
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
        if now - self.last_devices < 0.5:
            return
        if (
            self.restore_input == {"name": HAPLY_NAME, "ordinal": 0, "count": 1}
            and not self.last_status
        ):
            return  # Haply availability depends on the first robot-status response.
        self.last_devices = now
        devices = self.gamepads.devices() if self.gamepads else {}
        ids = [None, *devices, *(["haply"] if self.haply_supported() and haply_available() else [])]
        if ids == self.device_ids and self.restore_input is None:
            return
        selected = (
            "haply"
            if getattr(self, "haply", None)
            else (self.gamepads.selected if self.gamepads else None)
        )
        restore, self.restore_input = self.restore_input, None
        if restore:
            matching = [
                key for key, (_, raw) in devices.items() if controller_name(raw) == restore["name"]
            ]
            selected = matching[restore["ordinal"]] if len(matching) == restore["count"] else None
            if restore == {"name": HAPLY_NAME, "ordinal": 0, "count": 1} and "haply" in ids:
                selected = "haply"
        self.device_ids = ids
        names = [controller_name(name) for _, name in devices.values()]
        self.device["values"] = [
            "Keyboard",
            *[
                name + (f" · {index + 1}" if names.count(name) > 1 else "")
                for name, (index, _) in zip(names, devices.values(), strict=True)
            ],
            *([HAPLY_NAME] if "haply" in ids else []),
        ]
        self.device.current(ids.index(selected) if selected in ids else 0)
        if restore or selected not in ids:
            self.select_device()

    def drive(self, now):
        if self.switching_robot:
            return
        if self.haply:
            sample, _ = self.haply.sample(now)
            self.haply_input.calibration.observe(sample)
        if self.inputs:
            self.inputs.keyboard.poll(now)
        if not self.eligible():
            self.stop()
            if self.control.owned:
                self.control.release()
            return
        if not self.permitted():
            self.stop()
            return
        if self.replay.active:
            recording = self.replay_recording()
            if not self.root.winfo_viewable() or self.editing():
                self.stop("controller hidden or input controls changed")
            elif not recording or recording["id"] != self.replay.recording:
                self.stop("recording selection changed")
            return
        if self.replay.busy:
            return
        if not self.focused() or self.editing():
            self.stop()
            return
        robot = self.robots.get(self.selected)
        if not robot or not self.inputs:
            return
        state = self.control.feedback(robot)
        if self.pending_reset and self.control.ready:
            self.pending_reset = False
            self.control.move(self.selected, "reset", {}, None)
            return
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
            self.haply_input.halt()
            return
        if self.haply and not self.pointer_control:
            if not self.haply_supported():
                self.stop()
                return
            sample, self.haply_error = self.haply.sample(now)
            request = self.haply_input.update(
                sample, state, self.inputs, now, ready=self.control.ready
            )
            self.haply_error = self.haply_error or self.haply_input.error
        elif not self.control.ready:
            return
        elif self.device.current() == 0 or self.pointer_control:
            request = self.inputs.from_keyboard(now)
            if self.pointer_control and not self.inputs.keyboard.down:
                self.pointer_control = False
                self.inputs.halt()
        else:
            sample = self.gamepads.sample() if self.gamepads else None
            self.gamepad_sample = sample
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
                    self.inputs.cartesian_speed(command),
                    self.inputs.speed if self.inputs.controls.get("speed_deg_s") else None,
                )

    def feedback(self):
        robot = self.robots.get(self.selected, {})
        state = self.control.feedback(robot) if robot else {}
        if self.haply:
            _, error = self.haply.sample(time.monotonic())
            self.haply_error = error or self.haply_input.error
        owned = self.control.owned == self.selected and not self.control.releasing
        status = (
            "Active · " + (self.session.get("name", "you") if owned else robot["owner"])
            if owned or robot.get("owner")
            else "Available"
            if robot.get("status") == "online"
            else robot.get("status", self.session.get("status", "Disconnected")).title()
        )
        if state.get("home_active"):
            status += " · Going home…"
        elif state.get("stopping"):
            status += " · Stopping…"
        self.status_label.configure(text=status)
        mine = (
            owned
            or self.control.release_failed == self.selected
            or bool(self.session.get("id") and robot.get("owner_id") == self.session["id"])
        )
        for button, visible in (
            (self.release_button, mine),
            (self.acquire_button, not mine and not robot.get("owner")),
        ):
            if visible and not button.winfo_manager():
                button.pack(side="right", padx=self.px(8, 0))
            elif not visible:
                button.pack_forget()
        self.release_button.update_state(not self.control.releasing)
        self.acquire_button.update_state(
            not self.switching_robot and self.eligible() and self.control.ready
        )
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
        self.stop_button.update_state(self.permitted())
        self.home.update_state(
            available
            and not state.get("control_active")
            and bool(robot.get("controls", {}).get("home_deg"))
        )
        if robot.get("simulation") and robot.get("controls", {}).get("reset_scene"):
            if not self.reset_button.winfo_manager():
                self.reset_button.pack(
                    side="left",
                    before=self.replay_button
                    if self.replay_button.winfo_manager()
                    else self.stop_button,
                    padx=self.px(0, 8),
                )
            self.reset_button.update_state(
                self.permitted()
                and self.control.ready
                and not self.pending_reset
                and not robot.get("reset_scene_blocked")
            )
            self.reset_button.tooltip.text = {
                "mira-sim": "Reset both arms and the needle.",
                "franka-sim": "Reset the arm and probe to their starting positions.",
                "versius-sim": "Reset all four arms and the needle.",
            }.get(robot.get("kind"), "Reset scene") + (
                f" {robot['reset_scene_blocked']}" if robot.get("reset_scene_blocked") else ""
            )
        else:
            self.reset_button.pack_forget()
        recording = self.replay_recording()
        if recording and self.permitted():
            if not self.replay_button.winfo_manager():
                self.replay_button.pack(side="left", before=self.stop_button, padx=self.px(0, 8))
            self.replay_button.update_state(available and not self.replay.busy)
            self.replay_button.tooltip.text = (
                f"Replay {recording['device']} inputs · {recording['task']}"
            )
        else:
            self.replay_button.pack_forget()
        if self.replay.status and self.replay.robot == self.selected:
            self.replay_status.configure(text=self.replay.status)
            if not self.replay_status.winfo_manager():
                self.replay_status.pack(before=self.controls, fill="x", pady=self.px(0, 8))
        else:
            self.replay_status.pack_forget()
        if self.inputs and self.device.get() == HAPLY_NAME:
            self.haply_position.update_position(
                None
                if robot.get("stale")
                or robot.get("status") != "online"
                or now_stale(self.last_status)
                else self.haply_input.position_mm(state)
            )
            calibration = self.haply_input.calibration.status()
            sample, tracking_error = (
                self.haply.sample(time.monotonic())
                if self.haply
                else (None, "Connecting to Haply…")
            )
            self.range_button.configure(
                text="Save range" if calibration["collecting"] else "Calibrate movement range",
                state="normal" if sample is not None else "disabled",
            )
            if calibration["collecting"]:
                self.range_cancel.pack(anchor="w", after=self.range_button)
            else:
                self.range_cancel.pack_forget()
            self.range_hint.configure(
                text=tracking_error
                if sample is None
                else (
                    "Calibration active · Robot paused. "
                    "Sweep left/right, forward/back and up/down. Captured travel: "
                    + " / ".join(str(v) for v in calibration["span_mm"])
                    + " mm."
                    if calibration["collecting"]
                    else "Movement range saved. Center the pen, then tap Start."
                    if calibration["ready"]
                    else "Set the range once by sweeping the pen through its usable travel."
                )
            )
            self.haply_status.configure(
                text="Replay inputs"
                if self.replay.active
                else ("Paused" if self.haply_input.paused else "Active")
                + (f" · {self.haply_input.arm.title()} arm" if self.inputs.dual else "")
            )
        elif self.inputs and self.device.current() != 0:
            remaining = (
                max(0, 1 - (time.monotonic() - self.inputs.home_since))
                if self.inputs.home_since is not None
                else None
            )
            guidance = (
                self.error
                or self.control.error
                or robot.get("error")
                or (
                    "Replay · Stop / Esc to cancel"
                    if self.replay.active
                    else f"Keep holding · Home in {remaining:.1f}s"
                    if remaining is not None
                    else "Focus this window to control the robot."
                    if not self.focused()
                    else "Center sticks and release buttons to resume."
                    if not self.inputs.armed
                    else self.gamepad_guidance
                )
            )
            self.gamepad_status.configure(text=guidance)
            self.gamepad_status.tooltip.text = guidance
            for badge, binding in self.gamepad_badges:
                badge.update_state(
                    (available or self.replay.active) and self.gamepad_active(binding)
                )
        self.mode_choice.configure(
            state="readonly" if available else "disabled"
        ) if self.inputs else None
        for key, cap in self.keys.items():
            replay_keys = (self.replay.input or {}).get("keys", [])
            cap.update_state(
                available,
                (key in replay_keys if self.replay.active else key in self.inputs.keyboard.active)
                or (
                    (available or self.replay.active)
                    and key in self.gamepad_keys
                    and self.gamepad_active(("button", *self.gamepad_keys[key]))
                ),
            )
        for slider in self.sliders:
            slider.update_state(available)
        joints = state.get("joints_deg", state.get("targets_deg", {}))
        stale = robot.get("stale") or now_stale(self.last_status)
        for (group, index), label in self.positions.items():
            values = (
                state.get("cartesian_mm_deg", {}).get(group, [])
                if self.inputs.mode == "mira-tool" and self.device.current() == 0 and index < 4
                else joints.get(group, [])
            )
            label.configure(
                text=f"{values[index]:.{1 if robot.get('simulation') else 2}f}"
                if index < len(values) and not stale
                else "—"
            )
        for group, meter in self.grippers.items():
            value = state.get("grippers", {}).get(group)
            meter.delete("all")
            width = meter.winfo_width()
            text = f"{value * 100:.0f}%" if value is not None and not stale else "—"
            end = max(self.px(2), width - self.meter_font.measure(text) - self.px(7))
            meter.create_line(
                self.px(2),
                self.px(9),
                end,
                self.px(9),
                fill=BORDER,
                width=self.px(4),
                capstyle="round",
            )
            if value is not None and not stale and value > 0:
                meter.create_line(
                    self.px(2),
                    self.px(9),
                    self.px(2) + (end - self.px(2)) * max(0, min(1, value)),
                    self.px(9),
                    fill=GREEN,
                    width=self.px(4),
                    capstyle="round",
                )
            meter.create_text(
                width - self.px(1),
                self.px(9),
                anchor="e",
                text=text,
                font=self.meter_font,
                fill=MUTED,
            )
        self.message.configure(
            text=self.error
            or self.control.error
            or robot.get("error")
            or (self.haply_error if self.haply and not self.replay.active else "")
            or (
                ""
                if self.replay.active
                else "Acquire control to enable input."
                if not self.permitted()
                else "Focus this window to control the robot."
                if not self.focused()
                else ""
                if self.haply
                else "Center sticks and release buttons to resume."
                if self.device.current() != 0 and self.inputs and not self.inputs.armed
                else self.gamepad_error
            )
        )

    def close(self, retain_control=False):
        self.stop()
        self.return_control = retain_control
        self.returning_robot = self.control.owned if retain_control else None
        if not retain_control:
            self.control.release()
        self.closing = True
        self.message.configure(
            text="Returning control to dashboard…"
            if retain_control
            else "Stopping and releasing control…"
        )

    def shutdown(self):
        self.replay.close()
        self.control.close()
        self.worker.shutdown(wait=True, cancel_futures=True)
        if self.gamepads:
            self.gamepads.close()
        if self.haply:
            self.haply.close()


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
            config.get("input"),
            retain_control=config.get("retain_control") is True,
        )
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: window.close())
        signal.signal(signal.SIGUSR1, lambda *_: window.close(retain_control=True))
        report({"status": "running"})
        root.mainloop()
    except Exception as exc:
        report({"status": "error", "error": str(exc)})
        raise
    finally:
        if window:
            try:
                final_state = window.window_state("closed")
            except Exception:
                final_state = {"status": "closed"}
            finally:
                window.shutdown()
    report(final_state)


if __name__ == "__main__":
    run(json.loads(Path(sys.argv[1]).read_text()))
