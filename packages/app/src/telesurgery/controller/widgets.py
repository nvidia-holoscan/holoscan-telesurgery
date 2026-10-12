# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small Tk controls using the dashboard's colors and key-cap treatment."""

import math
import tkinter as tk
from tkinter import font, ttk

INK, MUTED, BORDER, GREEN = "#18211d", "#69756f", "#e1e5e4", "#659c13"
FONT = "Inter"


def dropdown_style(root):
    """Keep native dropdown behavior, with the dashboard's rounded field and chevron."""
    style = ttk.Style(root)
    style.theme_use("clam")

    def field(border, fill="white"):
        image = tk.PhotoImage(master=root, width=24, height=24)
        for y in range(24):
            for x in range(24):
                distance = math.hypot(max(6 - x, 0, x - 17), max(6 - y, 0, y - 17))
                if distance <= 6:
                    image.put(border if distance > 5 else fill, (x, y))
        return image

    def arrow(color):
        image = tk.PhotoImage(master=root, width=28, height=20)
        for x in range(9):
            y = 7 + min(x, 8 - x)
            image.put(color, to=(9 + x, y, 10 + x, y + 2))
        return image

    normal, focused = field("#d5ded2"), field(GREEN)
    disabled = field(BORDER, "#f6f8f7")
    chevron, muted_chevron = arrow(INK), arrow("#a8b0ab")
    style.element_create(
        "Controller.field",
        "image",
        normal,
        ("disabled", disabled),
        ("focus", focused),
        border=8,
        padding=0,
        sticky="nsew",
    )
    style.element_create(
        "Controller.chevron",
        "image",
        chevron,
        ("disabled", muted_chevron),
    )
    style.layout(
        "TCombobox",
        [
            (
                "Controller.field",
                {
                    "sticky": "nsew",
                    "children": [
                        ("Controller.chevron", {"side": "right", "sticky": ""}),
                        (
                            "Combobox.padding",
                            {
                                "sticky": "nsew",
                                "children": [
                                    ("Combobox.textarea", {"sticky": "nsew"}),
                                ],
                            },
                        ),
                    ],
                },
            ),
        ],
    )
    style.configure("TCombobox", padding=(10, 8, 0, 8), foreground=INK, background="white")
    style.configure("Control.TCombobox", background="#f6f8f7")
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", "white")],
        selectbackground=[("readonly", "white")],
        selectforeground=[("readonly", INK)],
        foreground=[("disabled", "#a8b0ab")],
    )
    for option, value in {
        "font": (FONT, 10),
        "background": "white",
        "foreground": INK,
        "selectBackground": "#eaf3df",
        "selectForeground": INK,
        "relief": "flat",
        "borderWidth": 0,
    }.items():
        root.option_add(f"*TCombobox*Listbox.{option}", value)
    return normal, focused, disabled, chevron, muted_chevron


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        widget.tooltip = self
        self.timer = self.window = None
        widget.bind("<Enter>", self.enter, add=True)
        for event in ("<Leave>", "<ButtonPress>", "<KeyPress>", "<Destroy>"):
            widget.bind(event, self.hide, add=True)

    def enter(self, _):
        self.hide()
        self.timer = self.widget.after(600, self.show)

    def show(self):
        self.timer = None
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.geometry(f"+{x}+{y}")
        tk.Label(
            self.window,
            text=self.text,
            font=(FONT, 9),
            fg=INK,
            bg="#fffde8",
            padx=6,
            pady=4,
            wraplength=260,
            justify="left",
            relief="solid",
            borderwidth=1,
        ).pack()

    def hide(self, _=None):
        if self.timer:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window:
            self.window.destroy()
            self.window = None


def rounded(canvas, x, y, width, height, radius=5, **options):
    return canvas.create_polygon(
        x + radius,
        y,
        x + width - radius,
        y,
        x + width,
        y,
        x + width,
        y + radius,
        x + width,
        y + height - radius,
        x + width,
        y + height,
        x + width - radius,
        y + height,
        x + radius,
        y + height,
        x,
        y + height,
        x,
        y + height - radius,
        x,
        y + radius,
        x,
        y,
        smooth=True,
        **options,
    )


class Button(tk.Canvas):
    def __init__(
        self,
        parent,
        text,
        command=None,
        *,
        width=64,
        color=INK,
        hold=None,
        icon=None,
        shortcut=None,
    ):
        super().__init__(
            parent,
            width=width,
            height=34,
            bg="white",
            highlightthickness=0,
            takefocus=True,
            cursor="hand2",
        )
        self.text, self.command, self.color, self.hold = text, command, color, hold
        self.icon = icon
        self.shortcut = shortcut
        self.label_font = font.Font(self, family=FONT, size=9) if shortcut else None
        self.enabled, self.pressed = True, False
        self.down = False
        self.space_down, self.space_timer = False, None
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<KeyPress-space>", self.space_press)
        self.bind("<KeyRelease-space>", self.space_release)
        self.bind(
            "<Destroy>", lambda _: self.after_cancel(self.space_timer) if self.space_timer else None
        )
        self.bind("<Return>", lambda _: self.command() if self.enabled and self.command else None)
        self.draw()

    def space_press(self, event):
        if self.space_timer:
            self.after_cancel(self.space_timer)
            self.space_timer = None
        if not self.space_down:
            self.space_down = True
            self.press(event)
        return "break"

    def space_release(self, event):
        if self.space_timer:
            self.after_cancel(self.space_timer)

        def released():
            self.space_down, self.space_timer = False, None
            self.release(event)

        self.space_timer = self.after(20, released)
        return "break"

    def draw(self):
        self.delete("all")
        width = max(self.winfo_width(), int(self.cget("width")))
        rounded(
            self,
            1,
            1,
            width - 3,
            31,
            fill="#e4f1cf" if self.pressed else "white",
            outline="#76b900" if self.pressed else "#cdd6cc",
        )
        color = self.color if self.enabled else "#a8b0ab"
        if self.icon == "home":
            # The dashboard's 24-unit Home outline, centered in a 20px icon.
            points = (
                3,
                10,
                12,
                3,
                21,
                10,
                21,
                20,
                20,
                21,
                15,
                21,
                15,
                13,
                9,
                13,
                9,
                21,
                4,
                21,
                3,
                20,
                3,
                10,
            )
            self.create_line(
                *[
                    width / 2 - 10 + value * 5 / 6 if index % 2 == 0 else 7 + value * 5 / 6
                    for index, value in enumerate(points)
                ],
                fill=color,
                width=1.5,
                capstyle="round",
                joinstyle="round",
            )
        elif self.shortcut:
            left = (width - self.label_font.measure(self.text) - 23) / 2
            self.create_rectangle(left, 8, left + 17, 25, fill="#f6f8f7", outline="#d7dfd3")
            self.create_text(left + 8.5, 17, text=self.shortcut, font=(FONT, 9, "bold"), fill=color)
            self.create_text(
                left + 23, 17, text=self.text, anchor="w", font=self.label_font, fill=color
            )
        else:
            self.create_text(
                width / 2,
                17,
                text=self.text,
                font=(FONT, 10, "bold"),
                fill=color,
            )

    def update_state(self, enabled=True, pressed=None, text=None):
        pressed = self.pressed if pressed is None else pressed
        text = self.text if text is None else text
        if (enabled, pressed, text) != (self.enabled, self.pressed, self.text):
            self.enabled, self.pressed, self.text = enabled, pressed, text
            self.draw()

    def press(self, event):
        if tooltip := getattr(self, "tooltip", None):
            tooltip.hide()
        if not self.enabled:
            return "break"
        self.focus_set()
        if not self.down:
            self.down = True
            self.pressed = True
            self.draw()
            if self.hold:
                self.hold(True)
        return "break"

    def release(self, event):
        if self.down:
            self.down = False
            self.pressed = False
            self.draw()
            if self.hold:
                self.hold(False)
            elif self.enabled and self.command:
                self.command()
        return "break"


class Slider(tk.Canvas):
    def __init__(self, parent, text, value, changed, minimum=1):
        super().__init__(
            parent, width=365, height=32, bg="white", highlightthickness=0, takefocus=True
        )
        self.text, self.value, self.changed, self.minimum = text, value, changed, minimum
        self.value_font = font.Font(self, family=FONT, size=9)
        self.enabled = True
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Button-1>", self.move)
        self.bind("<B1-Motion>", self.move)
        self.bind("<Left>", lambda _: self.set(self.value - 1))
        self.bind("<Right>", lambda _: self.set(self.value + 1))

    def set(self, value):
        if self.enabled:
            self.value = max(self.minimum, min(100, round(value)))
            self.changed(self.value)
            self.draw()
        return "break"

    def move(self, event):
        self.focus_set()
        start, end = self.track_bounds()
        return self.set(
            self.minimum + (100 - self.minimum) * (event.x - start) / max(1, end - start)
        )

    def label_left(self):
        return self.winfo_width() - self.value_font.measure("100%") - 1

    def track_bounds(self):
        return 96, max(97, self.label_left() - 12)

    def draw(self):
        self.delete("all")
        color = GREEN if self.enabled else "#a8b0ab"
        start, end = self.track_bounds()
        position = start + (end - start) * (self.value - self.minimum) / max(1, 100 - self.minimum)
        self.create_text(0, 16, anchor="w", text=self.text, font=(FONT, 10), fill=INK)
        self.create_line(90, 16, end + 6, 16, fill="#d7dfd3", width=4, capstyle="round")
        self.create_line(90, 16, position, 16, fill=color, width=4, capstyle="round")
        self.create_oval(position - 6, 10, position + 6, 22, fill=color, outline="white", width=2)
        self.create_text(
            self.label_left(), 16, anchor="w", text=f"{self.value}%", font=self.value_font, fill=INK
        )

    def update_state(self, enabled):
        if self.enabled != enabled:
            self.enabled = enabled
            self.draw()
