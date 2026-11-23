"""Estimate which side an observed imp fireball will pass on."""

from math import cos, radians, sin

LOOKAHEAD_TICS = 12
PASS_MARGIN = 32


def visible_fireballs(estimate):
    labels = estimate["labels"]
    if not estimate["active"] or labels is None:
        return None
    return {
        label["id"]: tuple(label["position"]) for label in labels if label["name"] == "DoomImpBall"
    }


class FireballTrack:
    def __init__(self):
        self.tic = None
        self.positions = {}

    def observe(self, estimate, current):
        tic = estimate["tics"]
        earlier_tic, earlier = self.tic, self.positions
        self.tic, self.positions = tic, current or {}
        if current is None:
            return None
        if not current:
            return "none"
        measurements = estimate["measurements"]
        x, y, angle = (measurements[key] for key in ("POSITION_X", "POSITION_Y", "ANGLE"))
        if earlier_tic != tic - 1 or None in (x, y, angle):
            return None

        heading = radians(angle)
        for identity, (px, py, _) in current.items():
            if identity not in earlier:
                continue
            before_x, before_y, _ = earlier[identity]
            dx, dy = px - before_x, py - before_y
            speed_squared = dx * dx + dy * dy
            if not speed_squared:
                continue
            tics_to_pass = ((x - px) * dx + (y - py) * dy) / speed_squared
            if not 0 < tics_to_pass <= LOOKAHEAD_TICS:
                continue
            pass_x, pass_y = px + tics_to_pass * dx - x, py + tics_to_pass * dy - y
            if pass_x * pass_x + pass_y * pass_y <= PASS_MARGIN**2:
                lateral = pass_y * cos(heading) - pass_x * sin(heading)
                return "left" if lateral > 0 else "right" if lateral < 0 else "center"
        return "none" if current.keys() <= earlier.keys() else None
