"""Observed planar motion shared by bounded Doom controllers."""

from math import hypot


def displacement(before, after):
    a, b = before["measurements"], after["measurements"]
    keys = ("POSITION_X", "POSITION_Y")
    if any(a[key] is None or b[key] is None for key in keys):
        return None
    return hypot(b["POSITION_X"] - a["POSITION_X"], b["POSITION_Y"] - a["POSITION_Y"])
