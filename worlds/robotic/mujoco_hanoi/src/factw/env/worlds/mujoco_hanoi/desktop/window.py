"""Place the robot view, controls, and SMSL readout in one Tk window."""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

PEGS = ("A", "B", "C")
PAPER = "#f4efe5"
PANEL = "#fffcf5"
INK = "#252922"
MUTED = "#5d6053"
RULE = "#d7ccba"
GREEN = "#294e43"
GREEN_PALE = "#dfebe0"
WHITE = "#fffcf5"
VIDEO_BG = "#1f2b28"
SERIF = "Times"
SANS = "Helvetica"
MONO = "DejaVu Sans Mono"
CAMERAS = (("overview", "Robot view"), ("overhead", "Overhead"))
BUTTON = "Hanoi.TButton"
SELECTED_BUTTON = "Selected.Hanoi.TButton"
PEG_BUTTON = "Peg.Hanoi.TButton"
SELECTED_PEG = "Selected.Peg.Hanoi.TButton"


def _text(parent, text="", *, bg=PAPER, fg=INK, font=(SANS, 10), **options):
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=font, anchor="w", **options)


def _rule(parent, *, background=RULE):
    return tk.Frame(parent, background=background, height=1)


def _style(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        BUTTON,
        background=PANEL,
        foreground=INK,
        bordercolor=RULE,
        focuscolor=GREEN,
        font=(SANS, 10, "bold"),
        padding=(11, 7),
    )
    style.map(
        BUTTON,
        background=[("active", GREEN_PALE)],
        foreground=[("disabled", MUTED)],
    )
    style.configure(PEG_BUTTON, padding=(9, 10), anchor="w")
    for selected in (SELECTED_BUTTON, SELECTED_PEG):
        style.configure(selected, background=GREEN, foreground=WHITE, focuscolor=WHITE)
        style.map(selected, background=[("active", "#365e50")])
    style.configure(
        "Hanoi.Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=INK,
        borderwidth=0,
        bordercolor=PANEL,
        lightcolor=PANEL,
        darkcolor=PANEL,
        rowheight=27,
        font=(MONO, 10),
    )
    style.configure(
        "Hanoi.Treeview.Heading",
        background=PAPER,
        foreground=MUTED,
        font=(SANS, 10, "bold"),
        relief="flat",
        borderwidth=0,
        padding=(5, 5),
    )


class HanoiWindow:
    def __init__(self, desktop):
        self.desktop = desktop
        self.agent = desktop.agent
        root = tk.Tk(className="HanoiDesktop")
        self.root = root
        root.title("Hanoi Agent — State Language" if self.agent else "Hanoi — State Language")
        root.configure(bg=PAPER)
        root.protocol("WM_DELETE_WINDOW", root.quit)
        width = min(1230, root.winfo_screenwidth() - 46)
        height = min(750, root.winfo_screenheight() - 74)
        root.geometry(f"{width}x{height}")
        root.minsize(min(820, width), min(585, height))
        _style(root)

        self._raw = None
        self._photo = None
        self._fact_state = None
        self._display_state = None
        self._header()
        body = tk.Frame(root, name="body", bg=PAPER)
        body.pack(fill="both", expand=True, padx=24, pady=(13, 18))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self._camera_panel(body)
        self._fact_panel(body)
        self.show_camera("overview")

    def _header(self):
        root = self.root
        bar = tk.Frame(root, name="header", bg=PAPER)
        bar.pack(fill="x", padx=24, pady=(16, 11))
        left = tk.Frame(bar, bg=PAPER)
        left.pack(side="left")
        _text(left, "Tower of Hanoi", font=(SERIF, 31)).pack(anchor="w")
        goal = self.desktop.session.goal
        if len(set(goal)) == 1:
            instruction = f"Move the full tower to peg {PEGS[goal[0]]}."
        else:
            positions = ", ".join(PEGS[peg] for peg in goal)
            instruction = f"Target pegs, smallest disk first · {positions}"
        _text(left, instruction, fg=MUTED, font=(SANS, 11)).pack(anchor="w", pady=(0, 2))

        right = tk.Frame(bar, bg=PAPER)
        right.pack(side="right", anchor="center")
        self.moves_text = _text(right, name="moves", font=(SERIF, 18))
        self.moves_text.pack(side="right", padx=(12, 0))
        mode = "Agent" if self.agent else "Player"
        _text(right, mode, bg=GREEN_PALE, fg=GREEN, font=(SANS, 10, "bold"), padx=10, pady=5).pack(
            side="right"
        )
        _rule(root).pack(fill="x", padx=24)

    def _camera_panel(self, body):
        view = tk.Frame(body, name="camera", bg=PAPER)
        view.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        camera_bar = tk.Frame(view, bg=PAPER)
        camera_bar.pack(fill="x", pady=(0, 8))
        _text(camera_bar, "MuJoCo simulation", font=(SERIF, 17)).pack(side="left")
        camera_buttons = tk.Frame(camera_bar, bg=PAPER)
        camera_buttons.pack(side="right")
        self.camera_buttons = {}
        for camera, title in CAMERAS:
            selector = ttk.Button(
                camera_buttons,
                name=camera,
                text=title,
                style=BUTTON,
                command=lambda camera=camera: self.desktop.select_camera(camera),
            )
            selector.pack(side="left", padx=(4, 0))
            self.camera_buttons[camera] = selector

        screen = tk.Frame(view, bg=VIDEO_BG)
        screen.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            screen, name="frame", bg=VIDEO_BG, highlightthickness=0, width=100, height=100
        )
        self.canvas.pack(fill="both", expand=True)
        self._image = self.canvas.create_image(0, 0)
        self.canvas.bind("<Configure>", self._resize)
        self.camera_state = _text(
            screen, name="camera_status", bg=VIDEO_BG, fg=WHITE, padx=12, pady=6
        )
        self.camera_state.pack(fill="x")

        self.action_text = _text(view, name="action", font=(SANS, 11, "bold"), justify="left")
        self.action_text.pack(fill="x", pady=(11, 6))
        view.bind("<Configure>", lambda event: self.action_text.configure(wraplength=event.width))
        if self.agent:
            self._agent_controls(view)
        else:
            self._player_controls(view)

    def _agent_controls(self, panel):
        row = tk.Frame(panel, bg=PAPER)
        row.pack(fill="x")
        self.pause = ttk.Button(
            row,
            name="pause",
            text="Pause",
            style=BUTTON,
            command=self.desktop.toggle_pause,
        )
        self.pause.pack(side="left")
        _text(row, "Pause to inspect the current frame and facts.", fg=MUTED).pack(
            side="left", padx=12
        )

    def _player_controls(self, panel):
        row = tk.Frame(panel, name="peg_controls", bg=PAPER)
        row.pack(fill="x")
        self.peg_buttons = []
        for peg, name in enumerate(PEGS):
            button = ttk.Button(
                row,
                name=f"peg_{name.lower()}",
                style=PEG_BUTTON,
                command=lambda peg=peg: self.desktop.choose_peg(peg),
            )
            button.grid(row=0, column=peg, sticky="ew", padx=(0, 6 if peg < len(PEGS) - 1 else 0))
            row.columnconfigure(peg, weight=1, uniform="pegs")
            self.peg_buttons.append(button)
            self.root.bind(str(peg + 1), lambda _event, peg=peg: self.desktop.choose_peg(peg))
        self.root.bind("<Escape>", lambda _event: self.desktop.cancel_selection())
        _text(panel, "Keys 1–3 select A–C · Esc clears the source", fg=MUTED).pack(
            fill="x", pady=(6, 0)
        )

    def _fact_panel(self, body):
        width = 350 if self.root.winfo_screenwidth() >= 1050 else 292
        panel = tk.Frame(
            body,
            name="facts",
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=RULE,
            width=width,
        )
        panel.grid(row=0, column=1, sticky="nsew")
        panel.pack_propagate(False)
        _text(panel, "State Language", bg=PANEL, font=(SERIF, 23)).pack(
            fill="x", padx=16, pady=(12, 4)
        )
        self.fact_status = _text(panel, name="facts_status", bg=PANEL, fg=MUTED)
        self.fact_status.pack(fill="x", padx=16, pady=(0, 9))

        table = tk.Frame(panel, bg=PANEL, name="board")
        table.pack(fill="x", padx=16)
        self.facts = ttk.Treeview(
            table,
            name="current",
            style="Hanoi.Treeview",
            columns=("name", "value"),
            show="headings",
            height=9,
            selectmode="none",
            takefocus=True,
        )
        self.facts.heading("name", text="Fact", anchor="w")
        self.facts.heading("value", text="Value", anchor="w")
        self.facts.column("name", anchor="w", stretch=True, minwidth=105, width=142)
        self.facts.column("value", anchor="w", stretch=True, minwidth=55, width=88)
        self.facts.tag_configure("changed", background=GREEN_PALE)
        self.facts.pack(fill="x")

        latest = tk.Frame(panel, name="latest", bg=GREEN_PALE)
        latest.pack(fill="x", padx=16, pady=(10, 11))
        _text(latest, "Latest fact changes", bg=GREEN_PALE, fg=GREEN, font=(SANS, 10, "bold")).pack(
            fill="x", padx=11, pady=(8, 2)
        )
        self.diff = _text(
            latest,
            name="changes",
            bg=GREEN_PALE,
            font=(MONO, 10),
            justify="left",
            wraplength=width - 55,
        )
        self.diff.pack(fill="x", padx=11, pady=(0, 8))
        _text(
            panel,
            "The arm reports its phase and finger contact. Pegs update after placement.",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=width - 40,
        ).pack(side="bottom", fill="x", padx=16, pady=(12, 12))

        self.history = tk.Frame(panel, name="history", bg=PANEL)
        _text(self.history, "Recent moves", bg=PANEL, fg=MUTED, font=(SANS, 10, "bold")).pack(
            fill="x", pady=(8, 4)
        )

    def show_camera(self, camera):
        for key, button in self.camera_buttons.items():
            button.configure(style=SELECTED_BUTTON if key == camera else BUTTON)
        title = dict(CAMERAS)[camera]
        self.camera_state.configure(text=f"{title}  ·  Franka Emika Panda")

    def show_frame(self, frame):
        self._raw = Image.fromarray(frame)
        self._resize()

    def _resize(self, _event=None):
        if self._raw is None:
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        factor = min(width / self._raw.width, height / self._raw.height)
        fit = (max(1, round(self._raw.width * factor)), max(1, round(self._raw.height * factor)))
        resized = self._raw.resize(fit, Image.Resampling.BILINEAR)
        self._photo = ImageTk.PhotoImage(resized, master=self.root)
        self.canvas.coords(self._image, width / 2, height / 2)
        self.canvas.itemconfigure(self._image, image=self._photo)

    def show_state(self, session, source, status, *, paused):
        fact_state = (dict(session.facts), dict(session.last_changes))
        if fact_state != self._fact_state:
            self._show_facts(*fact_state, moves=session.moves)
            self._fact_state = fact_state
        display = (
            session.moves,
            tuple(session.pegs),
            source,
            status,
            paused,
            session.active,
            session.phase,
            session.status,
            session.solved,
            session.failed,
            session.grasped,
        )
        if display != self._display_state:
            self._show_status(session, source, status, paused)
            self._display_state = display

    def _show_facts(self, facts, changes, *, moves):
        placed = [
            f"{name}  {_value(before)} → {_value(after)}"
            for name, (before, after) in changes.items()
            if name in {"small_peg", "medium_peg", "large_peg"}
        ]
        if placed:
            self.history.pack(fill="both", expand=True, padx=16)
            prior = self.history.winfo_children()
            line = _text(
                self.history,
                f"{moves}.  {', '.join(placed)}",
                bg=PANEL,
                font=(MONO, 9),
                justify="left",
            )
            line.pack(fill="x", pady=2, after=prior[0])
            if len(prior) > 5:
                prior[1].destroy()
        for item in self.facts.get_children():
            self.facts.delete(item)
        for name, value in facts.items():
            tags = ("changed",) if name in changes else ()
            self.facts.insert("", "end", values=(name, _value(value)), tags=tags)
        transitions = [
            f"{name}  {_value(before)} → {_value(after)}"
            for name, (before, after) in changes.items()
        ]
        self.diff.configure(text="\n".join(transitions) or "No moves yet")

    def _show_status(self, session, source, status, paused):
        noun = "move" if session.moves == 1 else "moves"
        self.moves_text.configure(text=f"{session.moves} {noun}")
        if session.failed:
            fact_status = "Last confirmed board · session stopped"
        elif session.grasped:
            fact_status = "Last confirmed board · disk in gripper"
        elif session.active and paused:
            fact_status = "Last confirmed board · motion paused"
        elif session.active:
            fact_status = "Last confirmed board · robot moving"
        else:
            fact_status = "Settled board facts"
        self.fact_status.configure(text=fact_status)
        if self.agent:
            self.pause.configure(text="Resume" if paused else "Pause")
            self.pause.state(["disabled" if session.solved or session.failed else "!disabled"])
        else:
            self._update_peg_buttons(session, source)
        if paused:
            message = "Paused"
        elif status:
            message = status
        elif session.solved or session.failed or session.active or self.agent:
            message = session.status
        elif source is None and session.phase == "placed":
            message = f"{session.status} Choose the next source."
        elif source is None:
            message = "Choose the peg to move from."
        else:
            message = f"Peg {PEGS[source]} selected. Choose the destination."
        self.action_text.configure(text=message)

    def _update_peg_buttons(self, session, source):
        disabled = session.active or session.solved or session.failed
        for peg, button in enumerate(self.peg_buttons):
            count = session.pegs.count(peg)
            disks = f"{count} disk" if count == 1 else f"{count} disks"
            detail = "source" if source == peg else disks
            style = SELECTED_PEG if source == peg else PEG_BUTTON
            button.configure(text=f"Peg {PEGS[peg]} · {detail}", style=style)
            button.state(["disabled" if disabled else "!disabled"])


def _value(value):
    if value is None:
        return "unknown"
    return str(value).lower() if isinstance(value, bool) else str(value)
