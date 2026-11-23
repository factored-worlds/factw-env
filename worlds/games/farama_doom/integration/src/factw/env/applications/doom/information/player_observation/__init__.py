"""Detached player-visible RGB captures without simulator metadata."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PlayerObservation:
    """One RGB capture; no telemetry, labels, depth, paths or evaluator truth."""

    capture_id: str
    rgb: np.ndarray


def player_observation(observation, *, capture_id):
    rgb = observation.rgb
    if (
        not isinstance(rgb, np.ndarray)
        or rgb.dtype != np.uint8
        or rgb.ndim != 3
        or rgb.shape[2] != 3
        or min(rgb.shape[:2]) < 1
    ):
        raise ValueError("Player view requires an available H×W×3 uint8 RGB capture")
    pixels = rgb.copy()
    pixels.flags.writeable = False
    return PlayerObservation(capture_id, pixels)
