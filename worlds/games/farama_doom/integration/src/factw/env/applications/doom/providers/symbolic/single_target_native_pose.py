"""Single-target sweep using grounded facts and native lateral position."""


class SweepPolicy:
    """Sweep laterally, pausing to fire; reverse after observed blocked movement."""

    def __init__(self):
        self.direction = "left"
        self.phase = 0
        self.previous_y = None
        self.previous_action = None

    def choose(self, view):
        facts = view["facts"]
        if not facts["active"]:
            return None
        if facts["won"]:
            return "wait"
        if not facts["alive"] or not facts["ammo"]:
            return None
        position_y = view["position_y"]
        if self.previous_action in ("left", "right") and abs(position_y - self.previous_y) < 0.5:
            self.direction = "right" if self.direction == "left" else "left"
        action = self.direction if self.phase % 4 == 0 else "shoot"
        self.phase += 1
        self.previous_y = position_y
        self.previous_action = action
        return action
