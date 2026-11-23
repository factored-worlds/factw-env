"""A read-only window showing the agent's last applied native command."""

from collections import deque

BUTTONS = (
    ("TURN_LEFT", "↶  Turn left", 0, 0),
    ("MOVE_FORWARD", "↑  Forward", 0, 1),
    ("TURN_RIGHT", "Turn right  ↷", 0, 2),
    ("MOVE_LEFT", "←  Strafe left", 1, 0),
    ("USE", "Use", 1, 1),
    ("MOVE_RIGHT", "Strafe right  →", 1, 2),
    ("ATTACK", "Fire", 2, 0),
)
BACKGROUND = "#111827"
PANEL = "#1f2937"
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
ACTIVE = "#67e8f9"


class ButtonWindow:
    def __init__(self):
        import tkinter as tk

        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            raise RuntimeError(
                "The Doom button window needs a desktop display; use --no-button-window "
                "to disable it."
            ) from error
        root = self.root
        root.title("Doom — Agent buttons")
        root.configure(bg=BACKGROUND)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.geometry(f"460x540+{max(0, root.winfo_screenwidth() - 480)}+40")
        self.history = deque(maxlen=6)

        def label(parent, text, *, size=11, color=TEXT, **options):
            return tk.Label(
                parent, text=text, bg=BACKGROUND, fg=color, font=("DejaVu Sans", size), **options
            )

        body = tk.Frame(root, bg=BACKGROUND, padx=20, pady=18)
        body.pack(fill="both", expand=True)
        label(body, "AGENT CONTROLS", size=10, color=ACTIVE).pack(anchor="w")
        label(body, "Last applied command", size=21).pack(anchor="w", pady=(4, 12))
        self.skill = label(body, "Waiting for the first game step", anchor="w")
        self.skill.pack(fill="x")
        self.progress = label(body, "Step 0", size=10, color=MUTED)
        self.progress.pack(anchor="w", pady=(4, 14))

        keys = tk.Frame(body, bg=BACKGROUND)
        keys.pack(fill="x")
        self.buttons = {}
        for name, title, row, column in BUTTONS:
            key = tk.Label(
                keys,
                text=f"{title}\n{name}",
                font=("DejaVu Sans", 10),
                bg=PANEL,
                fg=MUTED,
                height=3,
                relief="flat",
                borderwidth=2,
            )
            key.grid(
                row=row,
                column=column,
                columnspan=3 if name == "ATTACK" else 1,
                sticky="ew",
                padx=3,
                pady=3,
            )
            self.buttons[name] = key
        for column in range(3):
            keys.columnconfigure(column, weight=1, uniform="buttons")
        self.command = label(body, "No command sent", color=ACTIVE)
        self.command.pack(anchor="w", pady=(12, 14))
        label(body, "RECENT COMMANDS", size=10, color=MUTED).pack(anchor="w")
        self.recent = label(body, "", size=10, anchor="nw", justify="left", height=6)
        self.recent.pack(fill="x", pady=(5, 10))
        label(
            body,
            "Read-only · closing this window keeps the agent running.",
            size=9,
            color=MUTED,
        ).pack(anchor="w", side="bottom")
        root.update()

    def show(self, command, *, skill, step, tics, elapsed_seconds):
        if self.root is None:
            return
        pressed = {name for name, value in command["buttons"].items() if value != 0}
        for name, key in self.buttons.items():
            active = name in pressed
            key.configure(
                bg=ACTIVE if active else PANEL,
                fg=BACKGROUND if active else MUTED,
                relief="sunken" if active else "flat",
            )
        names = " + ".join(sorted(pressed)) if pressed else "NO BUTTONS"
        self.skill.configure(text=f"Skill: {skill.replace('_', ' ')}")
        self.progress.configure(
            text=f"Step {step}  ·  Game tic {tics}  ·  Applied for {elapsed_seconds * 1000:.0f} ms"
        )
        self.command.configure(text=names)
        self.history.appendleft(f"{step:>4}   {names}")
        self.recent.configure(text="\n".join(self.history))
        self.root.update()

    def close(self):
        if self.root is not None:
            self.root.destroy()
            self.root = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
