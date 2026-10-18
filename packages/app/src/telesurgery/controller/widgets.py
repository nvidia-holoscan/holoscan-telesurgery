# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Small Tk controls using the dashboard's colors and key-cap treatment."""

import math
import tkinter as tk
from tkinter import font, ttk

from telesurgery.controller.appearance import colors

INK, MUTED, BORDER, GREEN = "#18211d", "#69756f", "#e1e5e4", "#659c13"
FONT = "Inter"
FACE_POSITIONS = {"North": (0, -1), "South": (0, 1), "West": (-1, 0), "East": (1, 0)}


class ToolPosition(tk.Frame):
    """One axis triad and measured coordinates, independent of the robot model."""

    def __init__(self, parent, basis):
        super().__init__(parent, bg=colors(parent)("white"))
        px = Scale(parent)
        tk.Label(
            self,
            text="Arm tip · mm",
            bg=colors(parent)("white"),
            fg=colors(parent)(MUTED),
            font=(FONT, 9),
        ).pack(anchor="w")
        body = tk.Frame(self, bg=colors(parent)("white"))
        body.pack(fill="x")
        diagram = tk.Canvas(
            body, width=px(104), height=px(72), bg=colors(parent)("white"), highlightthickness=0
        )
        diagram.pack(side="left", padx=px(0, 18))
        rows = tk.Frame(body, bg=colors(parent)("white"))
        rows.pack(side="left")
        self.values = []
        axis_colors = ("#aa4e4e", "#427e59", "#477eac")
        directions = []
        for row in basis:
            x, y = row[0] + 0.72 * row[1], -0.69 * row[1] - row[2]
            length = max(1e-9, math.hypot(x, y))
            directions.append((x / length, y / length))
        bounds = [(0, 0)] + [(47 * x, 47 * y) for x, y in directions]
        xmin, xmax = min(x for x, _ in bounds) - 12, max(x for x, _ in bounds) + 12
        ymin, ymax = min(y for _, y in bounds) - 10, max(y for _, y in bounds) + 10
        scale = min(104 / (xmax - xmin), 72 / (ymax - ymin))

        def point(x, y):
            return px(
                (104 - (xmax + xmin) * scale) / 2 + x * scale,
                (72 - (ymax + ymin) * scale) / 2 + y * scale,
            )

        for axis, color, (x, y) in zip("XYZ", axis_colors, directions, strict=True):
            diagram.create_line(
                *point(0, 0),
                *point(34 * x, 34 * y),
                fill=colors(parent)(color),
                width=px(2),
                arrow="last",
                arrowshape=px(5, 6, 3),
            )
            diagram.create_text(
                *point(47 * x, 47 * y),
                text="+" + axis,
                fill=colors(parent)(color),
                font=(FONT, 9, "bold"),
            )
            row = tk.Frame(rows, bg=colors(parent)("white"))
            row.pack(fill="x")
            tk.Label(
                row,
                text=axis,
                bg=colors(parent)("white"),
                fg=colors(parent)(color),
                font=(FONT, 9, "bold"),
            ).pack(side="left")
            value = tk.Label(
                row,
                text="—",
                bg=colors(parent)("white"),
                fg=colors(parent)(INK),
                font=(FONT, 10),
                anchor="e",
                width=9,
            )
            value.pack(side="right")
            self.values.append(value)

    def update_position(self, position):
        for index, label in enumerate(self.values):
            value = position[index] if position is not None and len(position) > index else None
            label.configure(
                text=f"{0 if abs(value) < 0.05 else value:.1f}"
                if isinstance(value, (int, float)) and math.isfinite(value)
                else "—"
            )


class Scale:
    """Match custom pixel dimensions to the desktop's rendered font size.

    Xft can scale fonts independently of Tk's reported DPI (notably on XWayland).
    The 96-DPI layout uses a 19-pixel line for its 10-point body font.
    """

    def __init__(self, widget):
        reference = font.Font(widget, family=FONT, size=10)
        self.factor = max(1.0, reference.metrics("linespace") / 19)

    def __call__(self, *values):
        result = tuple(round(value * self.factor) for value in values)
        return result[0] if len(result) == 1 else result


def dropdown_style(root):
    """Keep native dropdown behavior, with the dashboard's rounded field and chevron."""
    px = Scale(root)
    style = ttk.Style(root)
    style.theme_use("clam")

    def field(border, fill="white"):
        border, fill = colors(root)(border), colors(root)(fill)
        image = tk.PhotoImage(master=root, width=px(24), height=px(24))
        for y in range(px(24)):
            for x in range(px(24)):
                dx, dy = x / px.factor, y / px.factor
                distance = math.hypot(max(6 - dx, 0, dx - 17), max(6 - dy, 0, dy - 17))
                if distance <= 6:
                    image.put(border if distance > 5 else fill, (x, y))
        return image

    def arrow(color):
        color = colors(root)(color)
        image = tk.PhotoImage(master=root, width=px(28), height=px(20))
        for x in range(px(9)):
            y = px(7) + min(x, px(9) - 1 - x)
            image.put(color, to=(px(9) + x, y, px(9) + x + 1, y + px(2)))
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
        border=px(8),
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
    line = font.Font(root, family=FONT, size=10).metrics("linespace")
    vertical = max(0, px(36) - line)
    style.configure(
        "TCombobox",
        padding=(px(8), vertical // 2, 0, vertical - vertical // 2),
        foreground=colors(root)(INK),
        background=colors(root)("white"),
    )
    style.configure("Control.TCombobox", background=colors(root)("#f6f8f7"))
    button_padding = max(0, px(36) - line - 4)
    style.configure(
        "TButton",
        font=(FONT, 10),
        relief="solid",
        borderwidth=1,
        padding=(px(8), button_padding // 2, px(8), button_padding - button_padding // 2),
        background=colors(root)("white"),
        foreground=colors(root)(INK),
        bordercolor=colors(root)(BORDER),
        lightcolor=colors(root)(BORDER),
        darkcolor=colors(root)(BORDER),
    )
    style.map(
        "TButton",
        background=[("active", colors(root)("#eaf3df"))],
        foreground=[("disabled", colors(root)(MUTED))],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=colors(root)("#f6f8f7"),
        troughcolor=colors(root)("white"),
        arrowcolor=colors(root)(MUTED),
        bordercolor=colors(root)(BORDER),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", colors(root)("white"))],
        selectbackground=[("readonly", colors(root)("white"))],
        selectforeground=[("readonly", colors(root)(INK))],
        foreground=[("disabled", colors(root)("#a8b0ab"))],
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
        root.option_add(
            f"*TCombobox*Listbox.{option}", colors(root)(value) if isinstance(value, str) else value
        )
    return normal, focused, disabled, chevron, muted_chevron


class ScrollArea(tk.Frame):
    """Scroll long device mappings while the robot selector and Stop stay in place."""

    def __init__(self, parent):
        super().__init__(parent, bg=colors(parent)("white"))
        # A 1px request can leave Tk's grid child unmapped after hiding the scrollbar.
        self.canvas = tk.Canvas(
            self, width=100, height=100, highlightthickness=0, bg=colors(parent)("white")
        )
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.content = tk.Frame(self.canvas, bg=colors(parent)("white"))
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.content.bind("<Configure>", self.resize)
        self.canvas.bind("<Configure>", self.resize)
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(event, self.wheel, add=True)

    def resize(self, _=None):
        self.canvas.itemconfigure(self.item, width=self.canvas.winfo_width())
        self.canvas.configure(scrollregion=self.canvas.bbox(self.item))
        if self.content.winfo_reqheight() > self.canvas.winfo_height():
            self.bar.grid(row=0, column=1, sticky="ns")
        else:
            self.bar.grid_remove()
            self.canvas.yview_moveto(0)

    def wheel(self, event):
        widget = event.widget
        if isinstance(widget, (ttk.Combobox, Slider)):
            return
        while widget is not None and widget is not self:
            widget = getattr(widget, "master", None)
        if widget is self and self.bar.winfo_ismapped():
            direction = -1 if event.num == 4 or getattr(event, "delta", 0) > 0 else 1
            self.canvas.yview_scroll(direction * 3, "units")
            return "break"


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.px = Scale(widget)
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
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.px(4)
        self.window.geometry(f"+{x}+{y}")
        tk.Label(
            self.window,
            text=self.text,
            font=(FONT, 9),
            fg=colors(self.widget)(INK),
            bg=colors(self.widget)("white"),
            padx=self.px(6),
            pady=self.px(4),
            wraplength=self.px(260),
            justify="left",
            relief="solid",
            borderwidth=self.px(1),
        ).pack()

    def hide(self, _=None):
        if self.timer:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.window:
            self.window.destroy()
            self.window = None


def rounded(canvas, x, y, box_width, box_height, radius=5, **options):
    return canvas.create_polygon(
        x + radius,
        y,
        x + box_width - radius,
        y,
        x + box_width,
        y,
        x + box_width,
        y + radius,
        x + box_width,
        y + box_height - radius,
        x + box_width,
        y + box_height,
        x + box_width - radius,
        y + box_height,
        x + radius,
        y + box_height,
        x,
        y + box_height,
        x,
        y + box_height - radius,
        x,
        y + radius,
        x,
        y,
        smooth=True,
        **options,
    )


def symbol(canvas, text, x, y, size, color, text_font):
    """Draw controller symbols with the same strong strokes as the web icons."""
    half, stroke = size / 2, max(1, size / 8)
    if text in FACE_POSITIONS:
        radius, offset = size / 8, size * 7 / 24
        for position, (dx, dy) in FACE_POSITIONS.items():
            cx, cy = x + dx * offset, y + dy * offset
            canvas.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                fill=colors(canvas)(color if position == text else ""),
                outline=colors(canvas)(color if position == text else MUTED),
                width=max(1, size / 16),
            )
    elif text == "□":
        canvas.create_rectangle(
            x - half, y - half, x + half, y + half, outline=colors(canvas)(color), width=stroke
        )
    elif text == "○":
        canvas.create_oval(
            x - half, y - half, x + half, y + half, outline=colors(canvas)(color), width=stroke
        )
    elif text == "△":
        canvas.create_polygon(
            x,
            y - half,
            x + half,
            y + half,
            x - half,
            y + half,
            fill="",
            outline=colors(canvas)(color),
            width=stroke,
        )
    elif text in {"←", "→", "↑", "↓"}:
        # Match the dashboard's 24-unit SVG paths and 2.5-unit stroke.
        head, shaft = {
            "←": ((10, 5, 3, 12, 10, 19), (3, 12, 21, 12)),
            "→": ((14, 5, 21, 12, 14, 19), (3, 12, 21, 12)),
            "↑": ((5, 10, 12, 3, 19, 10), (12, 3, 12, 21)),
            "↓": ((5, 14, 12, 21, 19, 14), (12, 3, 12, 21)),
        }[text]
        for points in (head, shaft):
            canvas.create_line(
                *[(x if i % 2 == 0 else y) + (v - 12) * size / 24 for i, v in enumerate(points)],
                fill=colors(canvas)(color),
                width=size * 2.5 / 24,
                capstyle="round",
                joinstyle="round",
            )
    else:
        canvas.create_text(x, y, text=text, font=text_font, fill=colors(canvas)(color))


class Badge(tk.Canvas):
    """Noninteractive gamepad binding, highlighted only while that input is active."""

    def __init__(self, parent, text):
        self.px = Scale(parent)
        # Use 16px direction glyphs; bold fallback fonts fill in their arrowheads.
        direction = text in {"↔", "↕"}
        self.text_font = font.Font(
            parent,
            family=FONT,
            size=12 if direction else 9,
            weight="normal" if direction else "bold",
        )
        self.text, self.active = text, False
        super().__init__(
            parent,
            width=self.px(28)
            if text in FACE_POSITIONS
            else max(self.px(28), self.text_font.measure(text) + self.px(12)),
            height=self.px(27),
            bg=colors(parent)("#f6f8f7"),
            highlightthickness=0,
            takefocus=False,
        )
        self.bind("<Configure>", lambda _: self.draw())
        self.draw()

    def draw(self):
        self.delete("all")
        width, height = max(self.winfo_width(), int(self.cget("width"))), self.px(27)
        rounded(
            self,
            self.px(1),
            self.px(1),
            width - self.px(3),
            height - self.px(3),
            radius=self.px(4),
            width=self.px(1),
            fill=colors(self)("#eaf3df" if self.active else "white"),
            outline=colors(self)("#76a443" if self.active else BORDER),
        )
        symbol(
            self,
            self.text,
            width / 2,
            height / 2,
            self.px(
                18
                if self.text in FACE_POSITIONS
                else 14
                if self.text in {"←", "→", "↑", "↓"}
                else 13
            ),
            "#365809" if self.active else INK,
            self.text_font,
        )

    def update_state(self, active):
        if self.active != active:
            self.active = active
            self.draw()


class Button(tk.Canvas):
    def __init__(
        self,
        parent,
        text,
        command=None,
        *,
        width=64,
        height=36,
        danger=False,
        color=INK,
        hold=None,
        icon=None,
        icon_text=False,
        shortcut=None,
    ):
        self.px = Scale(parent)
        self.text_font = font.Font(parent, family=FONT, size=9 if icon_text else 10, weight="bold")
        self.label_font = (
            font.Font(parent, family=FONT, size=9, weight="bold") if shortcut else None
        )
        text_width = (
            self.label_font.measure(text) + self.px(23)
            if shortcut
            else self.text_font.measure(text)
        )
        super().__init__(
            parent,
            width=max(self.px(width), text_width + self.px(39))
            if icon_text
            else max(self.px(width), text_width + self.px(12))
            if not icon
            else self.px(width),
            height=self.px(height),
            bg=colors(parent)("white"),
            highlightthickness=0,
            takefocus=True,
            cursor="hand2",
        )
        self.text, self.command, self.color, self.hold = text, command, color, hold
        self.icon = icon
        self.icon_text = icon_text
        self.danger = danger
        self.shortcut = shortcut
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
        px = self.px
        width = self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width"))
        height = self.winfo_height() if self.winfo_height() > 1 else int(self.cget("height"))
        rounded(
            self,
            px(1),
            px(1),
            width - px(3),
            height - px(3),
            radius=px(5),
            width=px(1),
            fill=colors(self)(
                "#eddad6"
                if self.danger and self.pressed
                else "#e4f1cf"
                if self.pressed
                else "white"
            ),
            outline=colors(self)(
                "#eddad6" if self.danger else "#76b900" if self.pressed else "#cdd6cc"
            ),
        )
        color = (
            "#a63735" if self.danger else self.color if self.enabled or self.pressed else "#a8b0ab"
        )
        icon_x = (
            (width - self.text_font.measure(self.text) - px(7)) / 2 if self.icon_text else width / 2
        )
        if self.icon_text:
            self.create_text(
                icon_x + px(15),
                height / 2,
                text=self.text,
                anchor="w",
                font=self.text_font,
                fill=colors(self)(color),
            )
        if self.icon == "home":
            # The dashboard's 24-unit Home outline, centered in a 16px icon.
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
                    icon_x + px(-8 + value * 2 / 3)
                    if index % 2 == 0
                    else height / 2 + px(-8 + value * 2 / 3)
                    for index, value in enumerate(points)
                ],
                fill=colors(self)(color),
                width=1.5 * px.factor,
                capstyle="round",
                joinstyle="round",
            )
        elif self.icon in {"acquire", "release"}:
            arrow = (13, 7, 8, 12, 13, 17) if self.icon == "acquire" else (16, 7, 21, 12, 16, 17)
            for points in ((9, 4, 4, 4, 4, 20, 9, 20), (8, 12, 21, 12), arrow):
                self.create_line(
                    *[
                        icon_x + px(-8 + value * 2 / 3)
                        if index % 2 == 0
                        else height / 2 + px(-8 + value * 2 / 3)
                        for index, value in enumerate(points)
                    ],
                    fill=colors(self)(color),
                    width=1.5 * px.factor,
                    capstyle="round",
                    joinstyle="round",
                )
        elif self.icon == "stop":
            self.create_rectangle(
                icon_x - px(6),
                height / 2 - px(6),
                icon_x + px(6),
                height / 2 + px(6),
                fill=colors(self)(color),
                outline="",
            )
        elif self.icon in {"reset", "replay"}:
            self.create_arc(
                icon_x - px(6),
                height / 2 - px(6),
                icon_x + px(6),
                height / 2 + px(6),
                start=160,
                extent=-310,
                style="arc",
                outline=colors(self)(color),
                width=1.5 * px.factor,
            )
            self.create_line(
                icon_x - px(6),
                height / 2 - px(6),
                icon_x - px(6),
                height / 2 - px(2),
                icon_x - px(2),
                height / 2 - px(2),
                fill=colors(self)(color),
                width=1.5 * px.factor,
                capstyle="round",
                joinstyle="round",
            )
            if self.icon == "replay":
                self.create_polygon(
                    icon_x - px(1),
                    height / 2 - px(3),
                    icon_x + px(3),
                    height / 2,
                    icon_x - px(1),
                    height / 2 + px(3),
                    fill="",
                    outline=colors(self)(color),
                    width=1.5 * px.factor,
                    joinstyle="round",
                )
        elif self.shortcut:
            left = (width - self.label_font.measure(self.text) - px(23)) / 2
            self.create_rectangle(
                left,
                px(8),
                left + px(17),
                px(25),
                fill=colors(self)("#f6f8f7"),
                outline=colors(self)("#d7dfd3"),
                width=px(1),
            )
            symbol(
                self,
                self.shortcut,
                left + px(8.5),
                px(17),
                px(
                    16
                    if self.shortcut in FACE_POSITIONS
                    else 14
                    if self.shortcut in {"←", "→", "↑", "↓"}
                    else 11
                ),
                color,
                (FONT, 9, "bold"),
            )
            self.create_text(
                left + px(23),
                px(17),
                text=self.text,
                anchor="w",
                font=self.label_font,
                fill=colors(self)(color),
            )
        else:
            self.create_text(
                width / 2,
                height / 2,
                text=self.text,
                font=self.text_font,
                fill=colors(self)(color),
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
        self.px = Scale(parent)
        super().__init__(
            parent,
            width=self.px(365),
            height=self.px(32),
            bg=colors(parent)("white"),
            highlightthickness=0,
            takefocus=True,
        )
        self.text, self.value, self.changed, self.minimum = text, value, changed, minimum
        self.value_font = font.Font(self, family=FONT, size=9)
        self.label_font = font.Font(self, family=FONT, size=9, weight="bold")
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
        return self.winfo_width() - self.value_font.measure("100%") - self.px(1)

    def track_bounds(self):
        start = max(self.px(96), self.label_font.measure(self.text) + self.px(18))
        return start, max(start + self.px(1), self.label_left() - self.px(12))

    def draw(self):
        self.delete("all")
        px = self.px
        color = GREEN if self.enabled else "#a8b0ab"
        start, end = self.track_bounds()
        position = start + (end - start) * (self.value - self.minimum) / max(1, 100 - self.minimum)
        self.create_text(
            0, px(16), anchor="w", text=self.text, font=self.label_font, fill=colors(self)(INK)
        )
        self.create_line(
            start - px(6),
            px(16),
            end + px(6),
            px(16),
            fill=colors(self)("#d7dfd3"),
            width=px(4),
            capstyle="round",
        )
        self.create_line(
            start - px(6),
            px(16),
            position,
            px(16),
            fill=colors(self)(color),
            width=px(4),
            capstyle="round",
        )
        self.create_oval(
            position - px(6),
            px(10),
            position + px(6),
            px(22),
            fill=colors(self)(color),
            outline=colors(self)("white"),
            width=px(2),
        )
        self.create_oval(
            position - px(7),
            px(9),
            position + px(7),
            px(23),
            outline=colors(self)(color),
            width=px(1),
        )
        self.create_text(
            self.label_left(),
            px(16),
            anchor="w",
            text=f"{self.value}%",
            font=self.value_font,
            fill=colors(self)(INK),
        )

    def update_state(self, enabled):
        if self.enabled != enabled:
            self.enabled = enabled
            self.draw()
