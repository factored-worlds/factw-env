"""Show a matched Doom frame and State Language snapshot during play."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

PAPER = "#f5f0e7"
PANEL = "#fffcf6"
TEXT = "#28241d"
MUTED = "#62574a"
RULE = "#d6cabb"
HIGHLIGHT = "#f7e8dd"
DARK = "#1c1815"
BODY = ("Helvetica", 10)
MONO = ("Courier", 10)
HEADING = ("Times", 19)
GAME_SIZES = ((800, 600), (640, 480), (512, 384), (400, 300), (320, 240))


def label(parent, text, *, background=PAPER, color=TEXT, font=BODY, **options):
    return tk.Label(parent, text=text, bg=background, fg=color, font=font, anchor="w", **options)


def fact_value(value):
    if value is None:
        return "unknown"
    return str(value).lower() if isinstance(value, bool) else str(value)


def fact_entries(groups):
    return [
        (f"{group.capitalize()}.{name}", value)
        for group, facts in groups.items()
        for name, value in facts.items()
    ]


def fact_table(parent, name, value_heading, height, *, narrow=False):
    tree = ttk.Treeview(
        parent,
        name=name,
        style="Doom.Treeview",
        columns=("fact", "value"),
        show="headings",
        height=height,
        selectmode="none",
    )
    tree.heading("fact", text="Fact", anchor="w")
    tree.heading("value", text=value_heading, anchor="w")
    tree.column("fact", width=150 if narrow else 210, minwidth=110 if narrow else 150, anchor="w")
    tree.column("value", width=118 if narrow else 145, minwidth=105 if narrow else 108, anchor="w")
    tree.tag_configure("changed", background=HIGHLIGHT)
    tree.tag_configure("unknown", foreground=MUTED)
    return tree


def default_game_resolution(width, height):
    game_width, game_height = next(
        (size for size in GAME_SIZES if size[0] <= width - 405 and size[1] <= height - 180),
        GAME_SIZES[-1],
    )
    return f"RES_{game_width}X{game_height}"


class LiveWindow:
    def __init__(self, on_close, *, human=False, game_resolution=None):
        self._human = human
        self._native_active = False
        app_name = "DoomHumanFacts" if human else "DoomAgent"
        root = tk.Tk(className=app_name)
        self.root = root
        root.tk.call("tk", "appname", app_name)
        root.title("Doom — State Language" if human else "Doom Agent — State Language")
        root.configure(bg=PAPER)
        root.protocol("WM_DELETE_WINDOW", on_close)
        width = min(1180, root.winfo_screenwidth() - 50)
        height = min(740, root.winfo_screenheight() - 85)
        self.game_resolution = game_resolution or default_game_resolution(width, height)
        self._compact = width < 1000
        root.geometry(f"{width}x{height}")
        root.minsize(min(740, width), min(480, height))

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "Doom.Treeview",
            background=PANEL,
            fieldbackground=PANEL,
            foreground=TEXT,
            font=("Courier", 9) if self._compact else MONO,
            rowheight=25,
            bordercolor=RULE,
            relief="flat",
        )
        style.configure("Doom.Treeview.Heading", background=PAPER, foreground=TEXT, font=BODY)

        header = tk.Frame(root, name="header", bg=PAPER)
        header.pack(fill="x", padx=22, pady=(15, 10))
        heading = label(header, "Doom" if human else "Doom agent", font=("Times", 29))
        self._status = label(header, "Preparing the Doom mission…", name="status", color=MUTED)
        heading.pack(side="left")
        self._status.pack(side="right", pady=(8, 0))
        tk.Frame(root, bg=RULE, height=1).pack(fill="x", padx=22)

        body = tk.Frame(root, name="body", bg=PAPER)
        body.pack(fill="both", expand=True, padx=22, pady=(15, 10))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        self._setup_scene(body)
        self._setup_state(body)
        footer = (
            "Close the window or press Ctrl+C in the terminal to save the recording."
            if human
            else "Closing this window leaves the agent running in the terminal."
        )
        label(root, footer, color=MUTED).pack(anchor="w", padx=22, pady=(0, 10))

        self._source_image = None
        self._photo = None
        self._episode = 0
        self._displayed_frame = None
        self._displayed_frame_step = None
        self._shown_change = None
        self._fact_rows = None

    def _setup_scene(self, body):
        scene = tk.Frame(body, name="scene", bg=PAPER)
        scene.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        label(scene, "Doom frame", font=HEADING).pack(fill="x", pady=(0, 7))
        self._frame = tk.Canvas(
            scene, name="frame", bg=DARK, highlightthickness=0, width=340 if self._compact else 500
        )
        self._image_item = self._frame.create_image(0, 0)
        self._frame.bind("<Configure>", self._resize_frame)
        self._frame_status = label(
            scene,
            "Waiting for the first captured frame",
            name="frame_status",
            background=DARK,
            color=PAPER,
            padx=10,
            pady=6,
        )
        self._frame.pack(fill="both", expand=True)
        self._frame_status.pack(fill="x")
        controls = tk.Frame(scene, bg=PAPER)
        controls.pack(fill="x", pady=(9, 0))
        hint = "WASD move · Mouse aim and fire · E use · Esc releases mouse" if self._human else ""
        self._command = label(controls, hint, name="controls", color=MUTED, justify="left")
        self._command.pack(side="left", fill="x", expand=True)

    def _setup_state(self, body):
        state = tk.Frame(
            body, name="state", bg=PANEL, highlightbackground=RULE, highlightthickness=1
        )
        state.grid(row=0, column=1, sticky="nsew")
        state.columnconfigure(0, weight=1)
        state.rowconfigure(4, weight=1)
        label(state, "State Language facts", background=PANEL, font=HEADING).grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(9, 4)
        )
        self._change_status = label(
            state,
            "Waiting for a fact change",
            name="change_status",
            background=PANEL,
            color=MUTED,
        )
        self._change_status.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 4))
        self._changes = fact_table(
            state,
            "changes",
            "Before and after",
            height=3 if self._compact else 4,
            narrow=self._compact,
        )
        self._changes.grid(row=2, column=0, sticky="nsew", padx=(12, 0))
        self._current_status = label(
            state,
            "Current facts",
            name="current_status",
            background=PANEL,
            color=MUTED,
        )
        self._current_status.grid(row=3, column=0, columnspan=2, sticky="ew", padx=12, pady=(11, 4))
        self._facts = fact_table(
            state, "facts", "Value", height=6 if self._compact else 10, narrow=self._compact
        )
        self._facts.grid(row=4, column=0, sticky="nsew", padx=(12, 0), pady=(0, 12))
        for row, table in ((2, self._changes), (4, self._facts)):
            scroll = ttk.Scrollbar(state, orient="vertical", command=table.yview, takefocus=False)
            scroll.grid(
                row=row, column=1, sticky="ns", padx=(0, 8), pady=(0, 12 if row == 4 else 0)
            )
            table.configure(yscrollcommand=scroll.set)

    @property
    def game_panel(self):
        return self._frame

    def set_native_active(self, active):
        if active == self._native_active:
            return
        self._native_active = active
        if active:
            self._frame_status.configure(text="Native game · Keyboard and mouse")
        elif self._displayed_frame is not None:
            self._show_frame(self._displayed_frame)
            self._frame_status.configure(
                text=f"Last captured frame · Step {self._displayed_frame_step}"
            )

    def _show_frame(self, path):
        with Image.open(path) as source:
            self._source_image = source.copy()
        self._resize_frame()

    def _resize_frame(self, event=None):
        source = self._source_image
        if source is None:
            return
        width, height = self._frame.winfo_width(), self._frame.winfo_height()
        if width <= 1 or height <= 1:
            return
        scale = min(width / source.width, height / source.height)
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        self._photo = ImageTk.PhotoImage(
            source.resize(size, Image.Resampling.NEAREST), master=self.root
        )
        self._frame.coords(self._image_item, width / 2, height / 2)
        self._frame.itemconfigure(self._image_item, image=self._photo)

    def status(self, text):
        self._status.configure(text=text)

    def finish(self, outcome):
        self.status(outcome)

    def render(self, step, latest_change):
        if self._human and step.episode != self._episode:
            self._episode = step.episode
            self._source_image = None
            self._photo = None
            self._displayed_frame = None
            self._displayed_frame_step = None
            self._frame.itemconfigure(self._image_item, image="")
        episode = f"Episode {step.episode + 1} · " if self._human and step.episode else ""
        self.status(f"Live · {episode}Step {step.index} · Tic {step.tic}")
        if step.rgb is not None:
            if step.rgb != self._displayed_frame and not self._native_active:
                self._show_frame(step.rgb)
            self._displayed_frame = step.rgb
            self._displayed_frame_step = step.index
            frame_status = f"Captured at step {step.index} · Tic {step.tic}"
        elif self._displayed_frame_step is not None:
            missing = (
                "Frame dropped"
                if step.frame_status in {"recorder_overload", "capture_queue_overload"}
                else "No frame"
            )
            frame_status = (
                f"{missing} at step {step.index} · Showing step {self._displayed_frame_step}"
            )
        elif step.frame_status in {"recorder_overload", "capture_queue_overload"}:
            frame_status = f"Frame dropped at step {step.index}"
        else:
            frame_status = f"No frame at step {step.index}"
        if self._native_active:
            frame_status = f"Native game · Facts sampled at tic {step.tic}"
        self._frame_status.configure(text=frame_status)

        if not self._human:
            self._render_controls(step)
        self._current_status.configure(text=f"Current facts · Step {step.index}")
        self._render_facts(step.facts)
        if latest_change is not None:
            timestamp = (
                f"Changed at step {step.index}"
                if latest_change.index == step.index
                else f"Most recent change · Step {latest_change.index}"
            )
            self._change_status.configure(text=timestamp)
            self._render_changes(latest_change)
        elif self._human and self._shown_change is not None:
            self._shown_change = None
            self._changes.delete(*self._changes.get_children())
            self._change_status.configure(text="Waiting for a fact change")

    def _render_controls(self, step):
        pressed = (
            []
            if step.command is None
            else [
                name.replace("_", " ").lower()
                for name, value in step.command["buttons"].items()
                if value
            ]
        )
        buttons = " + ".join(pressed) or "No buttons applied"
        skill = "" if step.skill is None else f"  ·  {step.skill.replace('_', ' ')}"
        self._command.configure(text=f"{buttons}{skill}")

    def _render_facts(self, facts):
        rows = fact_entries(facts)
        if rows == self._fact_rows:
            return
        names = {name for name, _ in rows}
        self._facts.delete(*(name for name in self._facts.get_children() if name not in names))
        self._fact_rows = rows
        for name, value in rows:
            contents = {
                "values": (name, fact_value(value)),
                "tags": ("unknown",) if value is None else (),
            }
            if self._facts.exists(name):
                self._facts.item(name, **contents)
            else:
                self._facts.insert("", "end", iid=name, **contents)

    def _render_changes(self, step):
        if step is self._shown_change:
            return
        self._shown_change = step
        self._changes.delete(*self._changes.get_children())
        for name, (before, after) in fact_entries(step.changes):
            self._changes.insert(
                "",
                "end",
                iid=name,
                values=(name, f"{fact_value(before)} -> {fact_value(after)}"),
                tags=("changed",),
            )
